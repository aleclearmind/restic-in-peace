from __future__ import annotations

import json
import os
import subprocess
import sys
from contextlib import ExitStack
from datetime import datetime
from pathlib import Path
from typing import IO

from . import diagnose
from . import profile as profile_mod
from .utils import human_numbers, logger


def _tee(text: str, sinks: list[IO[str]]) -> None:
    for sink in sinks:
        sink.write(text)
        sink.flush()


def _stream(cmd: list[str], sinks: list[IO[str]], env: dict[str, str] | None = None) -> int:
    """Run `cmd`, line-streaming its merged stdout/stderr to each sink. Returns the exit code."""
    process = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
        env=env,
    )
    assert process.stdout is not None
    for line in process.stdout:
        _tee(line, sinks)
    return process.wait()


def _profile_size_limit(config: dict, profile: str) -> int | None:
    """Resolve the profile and return its added-size-limit as bytes (or None)."""
    settings, _ = profile_mod.resolve(config, profile, "backup")
    raw = settings.get("added-size-limit")
    if raw is None:
        return None
    if isinstance(raw, int):
        return raw
    parsed: int = human_numbers.parse(str(raw))
    return parsed


def _exceeds_size_limit(
    config: dict,
    profile: str,
    items: list[tuple[str, int, int]],
    ncdu_doc: list | None,
    diag_path: Path | None,
    sinks: list[IO[str]],
) -> bool:
    limit = _profile_size_limit(config, profile)
    if limit is None or not items:
        return False
    total = sum(asize for _, asize, _ in items)
    if total <= limit:
        return False

    _tee(
        f"\nProfile {profile} would add {human_numbers.to_si(total)}, "
        f"exceeds added-size-limit {human_numbers.to_si(limit)}. "
        f"Skipping this profile.\n",
        sinks,
    )
    if diag_path is not None:
        _tee(f"To investigate:  ncdu --apparent-size -f {diag_path}\n", sinks)
    if ncdu_doc is not None:
        sigs = diagnose.significant_items(ncdu_doc)
        if sigs:
            _tee("Paths contributing ≥5% of the data to back up:\n", sinks)
            for path, size in sigs:
                _tee(f"  {human_numbers.to_si(size):>10s}  {path}\n", sinks)
    return True


def _print_summary(sinks: list[IO[str]], results: list[tuple[str, str]]) -> None:
    _tee("\n=== Summary ===\n", sinks)
    width = max((len(name) for name, _ in results), default=0)
    for name, status in results:
        _tee(f"  {name:<{width}}  {status}\n", sinks)


def _run_fix_home(config_path: str, sinks: list[IO[str]], sudo_user: str | None = None) -> int:
    """Verify that no fix-home action is pending for `sudo_user` (or the current user)."""
    prefix = ["sudo", "-Hu", sudo_user] if sudo_user else []
    cmd = prefix + ["restic-in-peace", "fix-home", "--strict", config_path]
    return _stream(cmd, sinks)


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
        wanted = set(only)
        unknown = wanted - set(profiles)
        if unknown:
            logger.error(
                f"--only references unknown profile(s): {sorted(unknown)}; "
                f"available: {profiles}"
            )
            return 1
        profiles = [p for p in profiles if p in wanted]
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

        fix_home_failed = False
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
                fix_home_failed = True
            else:
                results.append((f"fix-home/{fix_user}", "OK"))

        if fix_home_failed:
            _tee(
                "\nAborting: fix-home reported pending actions; not running any backup.\n"
                "Fix the home layout (or run `restic-in-peace fix-home <config> | bash`) and re-run.\n",
                sinks,
            )
            _print_summary(sinks, results)
            return 1

        for profile in profiles:
            _tee(f"Backing up profile {profile}\n", sinks)

            # Dry-run pre-pass: collect (path, asize, dsize) for every file
            # restic would add or modify, write the ncdu diagnostic, and use
            # the same data to enforce the profile's added-size-limit. If the
            # limit fires we skip this profile entirely — no `restic backup`
            # is ever started, so there's no SIGINT-during-upload window.
            diag_path: Path | None = None
            items: list[tuple[str, int, int]] = []
            ncdu_doc: list | None = None
            try:
                items = diagnose.collect_items(config, profile)
                ncdu_doc = diagnose.build_ncdu(items)
                if run_dir is not None:
                    diag_path = run_dir / f"{profile}.ncdu.json"
                    diag_path.parent.mkdir(parents=True, exist_ok=True)
                    diag_path.write_text(json.dumps(ncdu_doc) + "\n")
                    _tee(f"Wrote diagnostic to {diag_path}\n", sinks)
            except Exception as e:
                _tee(f"diagnostic for {profile} failed: {e}\n", sinks)
                logger.error(f"diagnostic for {profile} failed: {e}")

            if _exceeds_size_limit(config, profile, items, ncdu_doc, diag_path, sinks):
                results.append((profile, "size-limit exceeded; skipped"))
                continue

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
                settings, env_vars = profile_mod.resolve(config, profile, subcommand)
                flags, positionals = profile_mod.to_argv(
                    settings, subcommand, drop_keys=profile_mod.RIP_ONLY,
                )
                cmd = ["restic", subcommand] + flags + positionals
                if dry_run and subcommand in ("backup", "forget"):
                    cmd.append("--dry-run")
                proc_env = {**os.environ, **{k: str(v) for k, v in env_vars.items()}}
                rc = _stream(cmd, sinks, env=proc_env)
                if rc != 0:
                    _tee(f"{subcommand} for {profile} exited with {rc}\n", sinks)
                    profile_failure = (subcommand, rc)
                    break  # skip remaining subcommands for this profile

            if profile_failure is None:
                results.append((profile, "OK"))
            else:
                sub, rc = profile_failure
                results.append((profile, f"{sub} failed (exit {rc})"))

        _print_summary(sinks, results)

        failures = sum(1 for _, status in results if status != "OK")
        if failures:
            _tee(f"run-backup completed with {failures} failure(s)\n", sinks)
            return 1
    return 0
