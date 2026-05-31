from __future__ import annotations

import os
import sys
from pathlib import Path

import yaml

from . import profile as profile_mod


def log(message: str) -> None:
    sys.stderr.write(message + "\n")
    sys.stderr.flush()


def emit(message: str) -> None:
    sys.stdout.write(message + "\n")
    sys.stdout.flush()


def run(config_path: str, strict: bool = False) -> int:
    user = os.environ.get("USER") or os.environ.get("LOGNAME")
    if not user:
        log("Could not determine current user (USER/LOGNAME unset)")
        return 1

    try:
        config = profile_mod.load_config(config_path)
    except FileNotFoundError:
        log(f"Config file not found: {config_path}")
        return 1
    except yaml.YAMLError as e:
        log(f"Could not parse {config_path} as YAML: {e}")
        return 1

    try:
        configuration = config["fix-homes"][user]
    except KeyError:
        log(f"No fix-homes/{user} section in {config_path}")
        return 1

    home = Path.home()

    dot_files: set[Path] = set()

    if not strict:
        print("#!/usr/bin/env bash")
        print("set -euo pipefail")

    fail = False
    for destination_root, sources in sorted(configuration.items()):
        log(f"Handling {destination_root}")

        destination_root_path = home / destination_root

        if destination_root != "ignore" and not destination_root_path.exists():
            log(f"The destination does not exist!")
            return 1

        for source in sorted(sources):
            source_path = home / source
            dot_files.add(source_path)

            if destination_root == "ignore":
                continue

            destination = os.path.join(destination_root, source)
            destination_path = destination_root_path / source

            if source_path.exists() and destination_path.exists():
                if source_path.is_symlink():
                    symlink_destination = home / source_path.readlink()
                    if symlink_destination != destination_path:
                        log(f"    ERROR: Source is a symlink but points to the wrong file!")
                        log(f"      Source: {source}")
                        log(f"      Expected: {destination_path}")
                        log(f"      Actual: {symlink_destination}")
                        fail = True
                else:
                    log(f"    ERROR: Both source and destination exist but the source is not a symlink to the destination!")
                    log(f"      Source: {source}")
                    log(f"      Expected: {destination_path}")
                    fail = True
            elif source_path.exists():
                log(f"    Moving {source} to {destination_root}")
                if strict:
                    fail = True
                else:
                    emit(f'mv ~/"{source}" ~/"{destination}"')
                    emit(f'ln -s "{destination}" ~/"{source}"')
            elif destination_path.exists():
                log(f"    Linking {source} to {destination}")
                if strict:
                    fail = True
                else:
                    emit(f'ln -s "{destination}" ~/"{source}"')
            else:
                log(f"    ERROR: Neither source nor destination exist!")
                log(f"      Source: {source}")
                log(f"      Expected: {destination_path}")
                fail = True

    log("Checking ~/.*")
    for entry in home.iterdir():
        if entry.name.startswith(".") and entry not in dot_files:
            log(f"  ERROR: Unexpected file: {entry.name}")
            fail = True

    if fail:
        log("There were errors!")
        return 1

    log("Done")

    return 0
