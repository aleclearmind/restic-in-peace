from __future__ import annotations

import fnmatch
import json
import os
import subprocess
from pathlib import Path
from typing import Any, Callable

from . import profile as profile_mod
from .utils import log


# Top-level paths skipped when walking from /. Override the walk root entirely
# via RIP_COLLECT_ROOTS (colon-separated).
SYSTEM_DIRS: frozenset[str] = frozenset({
    "/nix", "/sys", "/proc", "/dev", "/bin", "/usr",
    "/tmp", "/lib", "/lib64", "/mnt", "/run",
})


def _run_restic(cmd: list[str], env_overrides: dict[str, str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
    env = {**os.environ, **env_overrides}
    return subprocess.run(cmd, env=env, **kwargs)


def _walk_roots() -> list[Path]:
    override = os.environ.get("RIP_COLLECT_ROOTS")
    if override:
        return [Path(p) for p in override.split(":") if p]
    return [p for p in Path("/").iterdir() if str(p) not in SYSTEM_DIRS]


def _collect_files(roots: list[Path]) -> set[str]:
    all_files: set[str] = set()
    for root in roots:
        for dirpath, _, filenames in os.walk(str(root), onerror=lambda e: None):
            all_files.update(os.path.join(dirpath, f) for f in filenames)
    return all_files


def _as_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    return list(value)


def _matches_exclude(path: str, pattern: str) -> bool:
    """Loose port of restic's exclude semantics for the implicit-classification
    heuristic. Faithful enough for the common cases, with two documented
    short-cuts:

    - restic's `**` (zero or more path segments) is not implemented. Patterns
      using it will under-match; affected files land in `implicit` rather than
      being filtered out, which is the right direction to err for a "did I
      forget anything?" report.
    - restic anchors a leading-`/` pattern to the source root, not the
      filesystem root. We don't have a back-reference to which source covers
      a given path, so we treat anchored patterns as absolute paths against
      the filesystem. Users writing `/cache` with source `/home/me` (meaning
      `/home/me/cache`) won't get a match.

    For everything else, we follow restic's per-sub-path semantics:
    - A pattern with no `/` is tested against each path component; restic's
      `*.tmp` matches `foo.tmp` whether it appears as a basename or as an
      ancestor directory name.
    - A pattern containing `/` is tested against each path suffix; restic's
      `foo/*.log` matches when a contiguous tail of the path matches.

    Python's `fnmatch.fnmatchcase` is permissive about `/` (its `*` matches
    `/`), but applied to single components or path suffixes the behavior
    coincides with restic's stricter `*` for these unit-of-matching cases.
    """
    if pattern.startswith("/"):
        return fnmatch.fnmatchcase(path, pattern)
    parts = path.split(os.sep)
    if "/" in pattern:
        return any(
            fnmatch.fnmatchcase(os.sep.join(parts[i:]), pattern)
            for i in range(len(parts))
        )
    return any(fnmatch.fnmatchcase(part, pattern) for part in parts)


def _build_explainer(
    config: dict[str, Any], profiles: list[str], all_files: set[str],
) -> Callable[[str], bool]:
    """Return `explained(path) -> bool` that answers "is this path's absence
    from the backup explained by some profile's exclude pattern or by a
    discovered exclude-if-present marker?". The negation drives the
    implicitly-non-backuped-files report."""
    excludes: list[str] = []
    markers: set[str] = set()
    for name in profiles:
        settings, _ = profile_mod.resolve(config, name, "backup")
        excludes.extend(_as_list(settings.get("exclude")))
        markers.update(_as_list(settings.get("exclude-if-present")))

    marker_dirs: set[str] = set()
    if markers:
        for f in all_files:
            parent, basename = os.path.split(f)
            if basename in markers:
                marker_dirs.add(parent)

    marker_prefixes = tuple(d + os.sep for d in marker_dirs)

    def explained(path: str) -> bool:
        if marker_prefixes and path.startswith(marker_prefixes):
            return True
        return any(_matches_exclude(path, p) for p in excludes)

    return explained


def run(config_path: str, output_dir: str) -> int:
    config_path = os.path.abspath(config_path)
    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    try:
        config = profile_mod.load_config(config_path)
    except profile_mod.ConfigError as e:
        log(str(e))
        return 1
    profiles = profile_mod.children_of(config, "common")

    backed_up: set[str] = set()
    log_files: list[Path] = []

    for profile in profiles:
        log(f"Collecting files backed up by {profile}")

        unlock_cmd, env = profile_mod.build_command(config, profile, "unlock")
        _run_restic(unlock_cmd, env, capture_output=True)

        backup_cmd, env = profile_mod.build_command(config, profile, "backup")
        # backup_cmd is ["restic", "backup", *flags, *sources]; insert the
        # dry-run options between the subcommand and the flags.
        backup_cmd[2:2] = ["--dry-run", "--verbose=2", "--json"]
        result = _run_restic(backup_cmd, env, capture_output=True, text=True)

        log_path = out_dir / f"{profile}.log.json"
        log_lines = [line for line in result.stdout.splitlines() if "message_type" in line]
        log_path.write_text("\n".join(log_lines) + "\n")
        log_files.append(log_path)

        for line in log_lines:
            try:
                msg = json.loads(line)
            except json.JSONDecodeError:
                continue
            if msg.get("action") == "new" and msg.get("item"):
                backed_up.add(msg["item"])

    (out_dir / "all-backuped-files").write_text("\n".join(sorted(backed_up)) + "\n")

    roots = _walk_roots()
    log(f"Collecting all files in {[str(r) for r in roots]}")
    all_files = _collect_files(roots)
    (out_dir / "all-files").write_text("\n".join(sorted(all_files)) + "\n")

    non_backed_up = sorted(all_files - backed_up)
    (out_dir / "non-backuped-files").write_text("\n".join(non_backed_up) + "\n")

    explained = _build_explainer(config, profiles, all_files)
    implicit = [p for p in non_backed_up if not explained(p)]
    (out_dir / "implicitly-non-backuped-files").write_text("\n".join(implicit) + "\n")

    for log_path in log_files:
        lines = log_path.read_text().splitlines()
        if len(lines) < 2:
            continue
        try:
            summary = json.loads(lines[-2])
        except json.JSONDecodeError:
            continue
        size = summary.get("data_added_packed", 0)
        print(f"{log_path}: {size // (1024**3)} GB")

    log("All done")
    return 0
