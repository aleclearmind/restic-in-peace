from __future__ import annotations

import json
import os
import subprocess
import time
from pathlib import Path, PurePosixPath
from typing import Any

from . import profile as profile_mod
from . import version


def collect_items(config: dict[str, Any], name: str) -> list[tuple[str, int]]:
    """Run `restic backup --dry-run --verbose=2 --json` for profile `name`
    and return [(path, size), ...] for every file restic would add.

    File sizes come from os.path.getsize(): restic's dry-run "new" events
    carry data_size=0 (nothing was actually added), so the JSON output is
    only good for the path list.
    """
    settings, env = profile_mod.resolve(config, name, "backup")
    flags, positionals = profile_mod.to_argv(settings, "backup", drop_keys=profile_mod.RIP_ONLY)
    # --no-lock so a stale lock from a previous run doesn't block the diagnostic.
    cmd = ["restic", "backup", "--dry-run", "--verbose=2", "--json", "--no-lock", *flags, *positionals]

    proc_env = os.environ.copy()
    proc_env.update({k: str(v) for k, v in env.items()})
    result = subprocess.run(cmd, env=proc_env, capture_output=True, text=True)

    # restic emits action="new" for files that aren't in any previous
    # snapshot and action="modified" for files whose content changed since
    # the last snapshot. Both contribute bytes to this backup; only
    # "unchanged" files (and the scan_finished event) don't.
    interesting_actions = {"new", "modified", "changed"}

    items: list[tuple[str, int]] = []
    for line in result.stdout.splitlines():
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            continue
        if msg.get("action") not in interesting_actions:
            continue
        item = msg.get("item")
        if not item or item.endswith("/"):
            # restic emits a status entry for each ancestor directory too;
            # skip them (ncdu computes directory totals from contents).
            continue
        try:
            size = os.path.getsize(item)
        except OSError:
            size = 0
        items.append((item, size))
    return items


def build_ncdu(items: list[tuple[str, int]]) -> list[Any]:
    """Build an ncdu v1.2 JSON document from a flat list of (file_path, size).

    ncdu format reference: https://dev.yorhel.nl/ncdu/jsonfmt
    - A file entry is `{"name": ..., "asize": <bytes>}`.
    - A directory entry is `[{"name": ..., }, child, child, [subdir-head, ...]]`.
    - ncdu computes a directory's displayed total by summing its descendants,
      so we deliberately leave `asize` off directory heads.
    """
    root: dict[str, Any] = {}

    for path, size in items:
        parts = PurePosixPath(path).parts
        if not parts:
            continue
        current = root
        for i, part in enumerate(parts):
            is_last = i == len(parts) - 1
            entry = current.setdefault(part, {"size": 0, "children": {}})
            if is_last:
                # Don't overwrite a directory we already saw (defensive).
                if not entry["children"]:
                    entry["size"] = size
                    entry["children"] = None
            else:
                if entry["children"] is None:
                    entry["children"] = {}
                current = entry["children"]

    def to_ncdu(name: str, entry: dict[str, Any]) -> Any:
        if entry["children"] is None:
            return {"name": name, "asize": entry["size"]}
        return [{"name": name}] + [to_ncdu(n, e) for n, e in sorted(entry["children"].items())]

    if len(root) == 1:
        name, entry = next(iter(root.items()))
        tree: Any = to_ncdu(name, entry)
    else:
        tree = [{"name": "rip-diagnostic"}] + [to_ncdu(n, e) for n, e in sorted(root.items())]

    return [
        1,
        2,
        {"progname": "restic-in-peace", "progver": version, "timestamp": int(time.time())},
        tree,
    ]


def write_diagnostic(config: dict[str, Any], name: str, output_path: Path) -> None:
    """Collect new items for `name` and write the ncdu JSON to output_path."""
    items = collect_items(config, name)
    document = build_ncdu(items)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(document) + "\n")
