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
    cmd = ["restic", "backup", "--dry-run", "--verbose=2", "--json", *flags, *positionals]

    proc_env = os.environ.copy()
    proc_env.update({k: str(v) for k, v in env.items()})
    result = subprocess.run(cmd, env=proc_env, capture_output=True, text=True)

    items: list[tuple[str, int]] = []
    for line in result.stdout.splitlines():
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            continue
        if msg.get("action") != "new":
            continue
        item = msg.get("item")
        if not item:
            continue
        try:
            size = os.path.getsize(item)
        except OSError:
            size = 0
        items.append((item, size))
    return items


def build_ncdu(items: list[tuple[str, int]]) -> list[Any]:
    """Build an ncdu v1.2 JSON document from a flat list of (path, size)."""
    root: dict[str, Any] = {}

    for path, size in items:
        parts = PurePosixPath(path).parts
        if not parts:
            continue
        current = root
        for i, part in enumerate(parts):
            is_last = i == len(parts) - 1
            entry = current.setdefault(part, {"size": 0, "children": {} if not is_last else None})
            if is_last:
                entry["size"] = size
                entry["children"] = None
            else:
                if entry["children"] is None:
                    entry["children"] = {}
                current = entry["children"]

    def compute_size(entry: dict[str, Any]) -> int:
        children = entry["children"]
        if children is None:
            return int(entry["size"])
        total = sum(compute_size(child) for child in children.values())
        entry["size"] = total
        return total

    for entry in root.values():
        compute_size(entry)

    def to_ncdu(name: str, entry: dict[str, Any]) -> Any:
        node = {"name": name, "asize": entry["size"]}
        if entry["children"] is None:
            return node
        return [node] + [to_ncdu(n, e) for n, e in sorted(entry["children"].items())]

    if len(root) == 1:
        name, entry = next(iter(root.items()))
        tree: Any = to_ncdu(name, entry)
    else:
        synthetic_size = sum(int(e["size"]) for e in root.values())
        tree = [{"name": "rip-diagnostic", "asize": synthetic_size}] + [
            to_ncdu(n, e) for n, e in sorted(root.items())
        ]

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
