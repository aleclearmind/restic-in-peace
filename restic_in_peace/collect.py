from __future__ import annotations

import json
import os
import re
import subprocess
from pathlib import Path
from typing import Any

from . import profile as profile_mod
from .utils import logger


# Top-level paths skipped when walking from /. Override the walk root entirely
# via RIP_COLLECT_ROOTS (colon-separated).
SYSTEM_DIRS: frozenset[str] = frozenset({
    "/nix", "/sys", "/proc", "/dev", "/bin", "/usr",
    "/tmp", "/lib", "/lib64", "/mnt", "/run",
})


def _restic_command(
    config: dict[str, Any],
    name: str,
    command: str,
    extra_args: tuple[str, ...] = (),
) -> tuple[list[str], dict[str, Any]]:
    settings, env = profile_mod.resolve(config, name, command)
    flags, positionals = profile_mod.to_argv(settings, command)
    return ["restic", command] + flags + list(extra_args) + positionals, env


def _run_restic(cmd: list[str], env_overrides: dict[str, Any], **kwargs: Any) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env.update({k: str(v) for k, v in env_overrides.items()})
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


def _build_filter(config: dict[str, Any], profiles: list[str], all_files: set[str]) -> re.Pattern[str] | None:
    excludes: list[str] = []
    sources: list[str] = []
    markers: set[str] = set()
    for name in profiles:
        settings, _ = profile_mod.resolve(config, name, "backup")

        excl = settings.get("exclude") or []
        if isinstance(excl, str):
            excl = [excl]
        excludes.extend(re.sub(r"\*", r".*", e) for e in excl)

        srcs = settings.get("source") or []
        if isinstance(srcs, str):
            srcs = [srcs]
        sources.extend(srcs)

        m = settings.get("exclude-if-present") or []
        if isinstance(m, str):
            m = [m]
        markers.update(m)

    parts = [e for e in excludes if e not in sources]

    if markers:
        marker_dirs: set[str] = set()
        for f in all_files:
            parent, name = os.path.split(f)
            if name in markers:
                marker_dirs.add(parent)
        parts.extend(sorted(marker_dirs))

    if not parts:
        return None
    return re.compile("^(" + "|".join(parts) + ")")


def run(config_path: str, output_dir: str) -> int:
    config_path = os.path.abspath(config_path)
    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    try:
        config = profile_mod.load_config(config_path)
    except profile_mod.ConfigError as e:
        logger.error(str(e))
        return 1
    profiles = profile_mod.children_of(config, "common")

    backed_up: set[str] = set()
    log_files: list[Path] = []

    for profile in profiles:
        logger.info(f"Collecting files backed up by {profile}")

        unlock_cmd, env = _restic_command(config, profile, "unlock")
        _run_restic(unlock_cmd, env, capture_output=True)

        backup_cmd, env = _restic_command(
            config, profile, "backup",
            extra_args=("--dry-run", "--verbose=2", "--json"),
        )
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
    logger.info(f"Collecting all files in {[str(r) for r in roots]}")
    all_files = _collect_files(roots)
    (out_dir / "all-files").write_text("\n".join(sorted(all_files)) + "\n")

    non_backed_up = sorted(all_files - backed_up)
    (out_dir / "non-backuped-files").write_text("\n".join(non_backed_up) + "\n")

    pattern = _build_filter(config, profiles, all_files)
    implicit = non_backed_up if pattern is None else [p for p in non_backed_up if not pattern.match(p)]
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

    logger.info("All done")
    return 0
