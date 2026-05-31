from __future__ import annotations

import os
import subprocess
import sys
from contextlib import ExitStack
from datetime import datetime
from pathlib import Path
from typing import IO

from . import profile as profile_mod
from .utils import logger


def _tee(text: str, sinks: list[IO[str]]) -> None:
    for sink in sinks:
        sink.write(text)
        sink.flush()


def _stream(cmd: list[str], sinks: list[IO[str]]) -> int:
    """Run `cmd`, line-streaming its merged stdout/stderr to each sink. Returns the exit code."""
    process = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )
    assert process.stdout is not None
    for line in process.stdout:
        _tee(line, sinks)
    return process.wait()


def _run_fix_home(config_path: str, sinks: list[IO[str]], sudo_user: str | None = None) -> int:
    """Verify that no fix-home action is pending for `sudo_user` (or the current user)."""
    prefix = ["sudo", "-Hu", sudo_user] if sudo_user else []
    cmd = prefix + ["restic-in-peace", "fix-home", "--strict", config_path]
    return _stream(cmd, sinks)


def run(config_path: str, dry_run: bool = False) -> int:
    config_path = os.path.abspath(config_path)
    try:
        config = profile_mod.load_config(config_path)
    except profile_mod.ConfigError as e:
        logger.error(str(e))
        return 1

    log_dir_str = config.get("run-backup", {}).get("log-path")
    fix_homes_users = list(config.get("fix-homes", {}).keys())
    profiles = profile_mod.children_of(config, "common")
    current_user = os.environ.get("USER") or os.environ.get("LOGNAME")

    with ExitStack() as stack:
        sinks: list[IO[str]]
        if log_dir_str:
            log_dir = Path(log_dir_str)
            log_dir.mkdir(parents=True, exist_ok=True)
            log_path = log_dir / datetime.now().strftime("%Y-%m-%d")
            log_file = stack.enter_context(log_path.open("a"))
            sinks = [sys.stdout, log_file]
        else:
            sinks = [sys.stderr]

        _tee(f"Starting backup on {datetime.now().ctime()}\n", sinks)

        for fix_user in fix_homes_users:
            _tee(f"Running fix-home for {fix_user}\n", sinks)
            rc = _run_fix_home(
                config_path,
                sinks,
                sudo_user=None if fix_user == current_user else fix_user,
            )
            if rc != 0:
                _tee(f"fix-home for {fix_user} exited with {rc}\n", sinks)
                return rc

        for profile in profiles:
            _tee(f"Backing up profile {profile}\n", sinks)
            subcommands: list[str] = []
            if not dry_run:
                subcommands.append("unlock")
            subcommands.append("backup")
            if profile_mod.has_section(config, profile, "forget"):
                subcommands.append("forget")
            if not dry_run:
                subcommands.append("check")

            for subcommand in subcommands:
                cmd = ["restic-in-peace", "--config", config_path, "--name", profile, subcommand]
                if dry_run and subcommand in ("backup", "forget"):
                    cmd.append("--dry-run")
                rc = _stream(cmd, sinks)
                if rc != 0:
                    _tee(f"{subcommand} for {profile} exited with {rc}\n", sinks)
                    return rc

    return 0
