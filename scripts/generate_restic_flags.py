#!/usr/bin/env python3
"""Parse `restic --help` (global + every subcommand) to extract every flag
name restic accepts, plus a JSON Schema fragment for each one.

Usage: generate_restic_flags.py <restic-binary> <output.json>
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any


# Captures the long flag name and (optional) value-type hint as restic prints
# them in `--help` output, e.g.
#     "      --cache-dir directory      set the cache directory ..."
#     "  -r, --repo repository          repository to backup to ..."
#     "      --json                     set output mode to JSON"
FLAG_RE = re.compile(r"^\s+(?:-\w,\s+)?--([\w-]+)(?:\s+(\S+))?")

# Boolean flags are followed by ≥2 spaces and the description; valued flags
# have exactly one space between the long form and the type word. We can't
# rely on column position so instead we whitelist restic's known type tokens —
# anything else after the flag is description text → boolean.
_TYPE_MAP: dict[str, dict[str, Any]] = {
    # scalar strings
    "string": {"type": "string"},
    "regex": {"type": "string"},
    "directory": {"type": "string"},
    "file": {"type": "string"},
    "hostname": {"type": "string"},
    "url": {"type": "string"},
    "duration": {"type": "string"},
    "repository": {"type": "string"},
    "pattern": {"type": "string"},
    "command": {"type": "string"},
    "mode": {"type": "string"},
    "size": {"type": "string"},
    "hint": {"type": "string"},
    "ID": {"type": "string"},
    "snapshotID": {"type": "string"},
    # array-like (each restic invocation accepts the flag once, but rip's YAML
    # accepts either a scalar or an array and translates accordingly)
    "strings": {"anyOf": [{"type": "string"}, {"type": "array", "items": {"type": "string"}}]},
    "stringArray": {"anyOf": [{"type": "string"}, {"type": "array", "items": {"type": "string"}}]},
    "tags": {"anyOf": [{"type": "string"}, {"type": "array", "items": {"type": "string"}}]},
    "taglist": {"anyOf": [{"type": "string"}, {"type": "array", "items": {"type": "string"}}]},
    "key=value": {"anyOf": [{"type": "string"}, {"type": "array", "items": {"type": "string"}}]},
    # numbers
    "n": {"type": "integer"},
    "int": {"type": "integer"},
    "uint": {"type": "integer"},
    "uint8": {"type": "integer"},
    "uint16": {"type": "integer"},
    "uint32": {"type": "integer"},
    "uint64": {"type": "integer"},
    "float32": {"type": "number"},
    "float64": {"type": "number"},
}

_BOOLEAN = {"type": "boolean"}


def _restic_help(restic_path: str, *args: str) -> str:
    return subprocess.run(
        [restic_path, *args, "--help"], capture_output=True, text=True, check=False
    ).stdout


def _parse_flags(help_text: str) -> dict[str, dict[str, Any]]:
    flags: dict[str, dict[str, Any]] = {}
    for line in help_text.splitlines():
        m = FLAG_RE.match(line)
        if not m:
            continue
        name, type_hint = m.groups()
        if name in ("help", "version"):
            continue
        flags[name] = _TYPE_MAP.get(type_hint, _BOOLEAN) if type_hint else _BOOLEAN
    return flags


def _list_commands(restic_path: str) -> list[str]:
    text = _restic_help(restic_path)
    commands: list[str] = []
    in_section = False
    for line in text.splitlines():
        if line.startswith("Available Commands"):
            in_section = True
            continue
        if not in_section:
            continue
        if not line.strip():
            break
        parts = line.split(None, 1)
        if not parts:
            continue
        cmd = parts[0]
        if re.fullmatch(r"[a-z][a-z-]*", cmd):
            commands.append(cmd)
    return commands


def collect(restic_path: str) -> dict[str, dict[str, Any]]:
    flags: dict[str, dict[str, Any]] = _parse_flags(_restic_help(restic_path))
    for cmd in _list_commands(restic_path):
        for name, schema in _parse_flags(_restic_help(restic_path, cmd)).items():
            flags.setdefault(name, schema)
    return flags


def main() -> int:
    if len(sys.argv) != 3:
        sys.stderr.write(
            "Usage: generate_restic_flags.py <restic-binary> <output.json>\n"
        )
        return 2

    restic_path, output_path = sys.argv[1], sys.argv[2]
    flags = collect(restic_path)
    payload = {"flags": flags}
    Path(output_path).write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
