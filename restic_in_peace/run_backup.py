from __future__ import annotations

import os
import subprocess
import sys
from contextlib import ExitStack
from datetime import datetime
from pathlib import Path
from typing import IO

from . import diagnose
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


def _filter_by_tags(config: dict, profiles: list[str], only: list[str]) -> list[str]:
    """Keep profiles whose resolved backup.tag matches any of `only`."""
    wanted = set(only)
    kept: list[str] = []
    for profile in profiles:
        settings, _ = profile_mod.resolve(config, profile, "backup")
        tag = settings.get("tag")
        if isinstance(tag, str):
            tags = {tag}
        elif isinstance(tag, list):
            tags = set(tag)
        else:
            tags = set()
        if tags & wanted:
            kept.append(profile)
    return kept


def run(
    config_path: str,
    dry_run: bool = False,
    log_path: str | None = None,
    only: list[str] | None = None,
) -> int:
    config_path = os.path.abspath(config_path)
    try:
        config = profile_mod.load_config(config_path)
    except profile_mod.ConfigError as e:
        logger.error(str(e))
        return 1

    log_dir_str = log_path or config.get("run-backup", {}).get("log-path")
    fix_homes_users = list(config.get("fix-homes", {}).keys())
    profiles = profile_mod.children_of(config, "common")
    if only:
        profiles = _filter_by_tags(config, profiles, only)
    current_user = os.environ.get("USER") or os.environ.get("LOGNAME")

    run_dir: Path | None = None
    if log_dir_str:
        run_dir = Path(log_dir_str) / datetime.now().strftime("%Y-%m-%d-%H-%M-%S")
        run_dir.mkdir(parents=True, exist_ok=False)

    with ExitStack() as stack:
        sinks: list[IO[str]]
        if run_dir is not None:
            log_file = stack.enter_context((run_dir / "backup.log").open("a"))
            sinks = [sys.stdout, log_file]
        else:
            sinks = [sys.stderr]

        _tee(f"Starting backup on {datetime.now().ctime()}\n", sinks)

        results: list[tuple[str, str]] = []

        for fix_user in fix_homes_users:
            _tee(f"Running fix-home for {fix_user}\n", sinks)
            rc = _run_fix_home(
                config_path,
                sinks,
                sudo_user=None if fix_user == current_user else fix_user,
            )
            if rc != 0:
                _tee(f"fix-home for {fix_user} exited with {rc}\n", sinks)
                results.append((f"fix-home/{fix_user}", f"failed (exit {rc})"))
            else:
                results.append((f"fix-home/{fix_user}", "OK"))

        for profile in profiles:
            _tee(f"Backing up profile {profile}\n", sinks)

            # Always write a per-profile ncdu diagnostic of what restic would
            # add, before the real backup. Useful regardless of outcome (real
            # run or --dry-run, success or size-limit abort).
            if run_dir is not None:
                diag_path = run_dir / f"{profile}.ncdu.json"
                _tee(f"Writing diagnostic to {diag_path}\n", sinks)
                try:
                    diagnose.write_diagnostic(config, profile, diag_path)
                except Exception as e:
                    _tee(f"diagnostic for {profile} failed: {e}\n", sinks)
                    logger.error(f"diagnostic for {profile} failed: {e}")

            subcommands: list[str] = []
            if not dry_run:
                subcommands.append("unlock")
            subcommands.append("backup")
            if profile_mod.has_section(config, profile, "forget"):
                subcommands.append("forget")
            if not dry_run:
                subcommands.append("check")

            profile_failure: tuple[str, int] | None = None
            for subcommand in subcommands:
                cmd = ["restic-in-peace", "--config", config_path, "--name", profile, "restic", subcommand]
                if dry_run and subcommand in ("backup", "forget"):
                    cmd.append("--dry-run")
                rc = _stream(cmd, sinks)
                if rc != 0:
                    _tee(f"{subcommand} for {profile} exited with {rc}\n", sinks)
                    profile_failure = (subcommand, rc)
                    break  # skip remaining subcommands for this profile

            if profile_failure is None:
                results.append((profile, "OK"))
            else:
                sub, rc = profile_failure
                results.append((profile, f"{sub} failed (exit {rc})"))

        _tee("\n=== Summary ===\n", sinks)
        width = max((len(name) for name, _ in results), default=0)
        for name, status in results:
            _tee(f"  {name:<{width}}  {status}\n", sinks)

        failures = sum(1 for _, status in results if status != "OK")
        if failures:
            _tee(f"run-backup completed with {failures} failure(s)\n", sinks)
            return 1
    return 0
