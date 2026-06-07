from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from contextlib import ExitStack
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import IO

from . import diagnose
from . import profile as profile_mod
from .utils import battery, human_numbers, log, network


def _notify(enabled: bool, summary: str, body: str = "", urgent: bool = False) -> None:
    """Fire a notify-send notification when `enabled`. Silent if notify-send
    isn't on PATH or fails — notifications are best-effort."""
    if not enabled or shutil.which("notify-send") is None:
        return
    cmd = ["notify-send", "--app-name=restic-in-peace"]
    if urgent:
        cmd.append("--urgency=critical")
    cmd.append(summary)
    if body:
        cmd.append(body)
    try:
        subprocess.run(cmd, check=False)
    except OSError:
        pass


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


def _frequency(config: dict) -> timedelta | None:
    raw = profile_mod.rip_settings(config).get("frequency")
    if raw is None:
        return None
    return human_numbers.parse_duration(str(raw))


def _parse_restic_time(s: str) -> datetime:
    """Parse restic's RFC3339 timestamp. restic emits nanoseconds, which
    stdlib's fromisoformat can't handle; truncate the fractional part to 6
    digits before parsing."""
    m = re.match(
        r"^(?P<head>\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})"
        r"(?:\.(?P<frac>\d{1,9}))?"
        r"(?P<tail>Z|[+-]\d{2}:?\d{2})?$",
        s,
    )
    if m is None:
        return datetime.fromisoformat(s)
    head = m.group("head")
    frac = (m.group("frac") or "")[:6]
    tail = m.group("tail") or ""
    if tail == "Z":
        tail = "+00:00"
    iso = f"{head}.{frac}{tail}" if frac else f"{head}{tail}"
    return datetime.fromisoformat(iso)


def _latest_snapshot_time(config: dict, profile: str) -> datetime | None:
    """Run `restic snapshots --tag <profile> --json --no-lock --latest 1` and
    return the newest snapshot's timestamp. Returns None if the tag has no
    snapshots yet. Raises if the restic call fails or the output can't be
    parsed — the orchestrator turns those into profile failures."""
    cmd, env = profile_mod.build_command(config, profile, "snapshots")
    cmd.extend(["--tag", profile, "--no-lock", "--json", "--latest", "1"])
    result = subprocess.run(
        cmd,
        env={**os.environ, **env},
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"restic snapshots exited {result.returncode}: {result.stderr.strip()}"
        )
    snapshots = json.loads(result.stdout) if result.stdout.strip() else []
    if not snapshots:
        return None
    latest = max(snapshots, key=lambda s: s["time"])
    return _parse_restic_time(latest["time"])


def _size_limit_bytes(config: dict) -> int | None:
    """Return the rip-wide added-size-limit as bytes, or None if unset."""
    raw = profile_mod.rip_settings(config).get("added-size-limit")
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
    limit = _size_limit_bytes(config)
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


def _print_summary(
    sinks: list[IO[str]],
    results: list[tuple[str, str, int | None, Path | None]],
) -> None:
    """Each row is (name, status, would_add_bytes_or_None, diag_path_or_None).
    When the row is a size-limit skip and we know the diagnostic path, we
    print the ncdu invocation right under it."""
    _tee("\n=== Summary ===\n", sinks)
    name_w = max((len(n) for n, *_ in results), default=0)
    size_w = max(
        (len(human_numbers.to_si(b)) for _, _, b, _ in results if b is not None),
        default=0,
    )
    for name, status, would_add, diag in results:
        size_col = (
            f"{human_numbers.to_si(would_add):>{size_w}}" if would_add is not None
            else " " * size_w
        )
        _tee(f"  {name:<{name_w}}  {size_col}  {status}\n", sinks)
        if "size-limit exceeded" in status and diag is not None:
            _tee(f"  {' ' * name_w}  {' ' * size_w}  ncdu --apparent-size -f {diag}\n", sinks)


def _run_fix_home(config_path: str, sinks: list[IO[str]], sudo_user: str | None = None) -> int:
    """Verify that no fix-home action is pending for `sudo_user` (or the current user)."""
    prefix = ["sudo", "-Hu", sudo_user] if sudo_user else []
    cmd = prefix + ["rip", "--config", config_path, "fix-home", "--strict"]
    return _stream(cmd, sinks)


def run(
    config_path: str,
    dry_run: bool = False,
    log_path: str | None = None,
    only: list[str] | None = None,
    ignore_skip_on_battery: bool = False,
    ignore_added_size_limit: bool = False,
    ignore_wifi_whitelist: bool = False,
    ignore_frequency: bool = False,
) -> int:
    config_path = os.path.abspath(config_path)
    try:
        config = profile_mod.load_config(config_path)
    except profile_mod.ConfigError as e:
        log(str(e))
        return 1

    rip = profile_mod.rip_settings(config)
    notify_on = bool(rip.get("desktop-notifications", False))
    skip_on_battery = bool(rip.get("skip-on-battery", False)) and not ignore_skip_on_battery
    if not battery.battery_ok(skip_on_battery):
        log("On battery power; skipping the whole run.")
        return 1
    whitelist = [] if ignore_wifi_whitelist else rip.get("wifi-whitelist", [])
    if not network.network_ok(
        blacklist=rip.get("wifi-blacklist", []),
        whitelist=whitelist,
    ):
        log("Network conditions don't allow backup; skipping the whole run.")
        return 1

    log_dir_str = log_path or config.get("log-path")
    fix_homes_users = list(config.get("fix-homes", {}).keys())
    profiles = profile_mod.children_of(config, "common")
    if only:
        wanted = set(only)
        unknown = wanted - set(profiles)
        if unknown:
            log(
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
        _notify(notify_on, "Backup started",
            f"{len(profiles)} profile(s); fix-home for {len(fix_homes_users)} user(s)")

        # results entry: (name, status, would_add_bytes_or_None, diag_path_or_None)
        results: list[tuple[str, str, int | None, Path | None]] = []

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
                results.append((f"fix-home/{fix_user}", f"failed (exit {rc})", None, None))
                fix_home_failed = True
            else:
                results.append((f"fix-home/{fix_user}", "OK", None, None))

        if fix_home_failed:
            _tee(
                "\nAborting: fix-home reported pending actions; not running any backup.\n"
                "Fix the home layout (or run `rip fix-home | bash`) and re-run.\n",
                sinks,
            )
            _print_summary(sinks, results)
            _notify(notify_on, "Backup aborted",
                "fix-home reported pending actions", urgent=True)
            return 1

        frequency = None if ignore_frequency else _frequency(config)

        for profile in profiles:
            _tee(f"Backing up profile {profile}\n", sinks)

            if frequency is not None:
                try:
                    latest = _latest_snapshot_time(config, profile)
                except Exception as e:
                    _tee(f"snapshot query for {profile} failed: {e}\n", sinks)
                    results.append((profile, f"snapshot query failed: {e}", None, None))
                    _notify(notify_on, f"Backup failed: {profile}",
                        f"could not query latest snapshot: {e}", urgent=True)
                    continue
                if latest is not None:
                    age = datetime.now(timezone.utc) - latest
                    if age < frequency:
                        age_str = human_numbers.format_duration(age)
                        freq_str = human_numbers.format_duration(frequency)
                        _tee(
                            f"{profile}: last snapshot {age_str} ago "
                            f"(< frequency {freq_str}); skipping\n",
                            sinks,
                        )
                        results.append(
                            (profile, f"up-to-date (last {age_str} ago)", None, None)
                        )
                        continue

            # Dry-run pre-pass: collect (path, asize, dsize) for every file
            # restic would add or modify, write the ncdu diagnostic, and use
            # the same data to enforce the profile's added-size-limit. If the
            # limit fires we skip this profile entirely — no `restic backup`
            # is ever started, so there's no SIGINT-during-upload window.
            diag_path: Path | None = None
            items: list[tuple[str, int, int]] = []
            ncdu_doc: list | None = None
            try:
                _tee(f"Dry-run pre-pass for {profile} (this can take a while)...\n", sinks)
                items = diagnose.collect_items(config, profile, progress_sinks=sinks)
                ncdu_doc = diagnose.build_ncdu(items)
                if run_dir is not None:
                    diag_path = run_dir / f"{profile}.ncdu.json"
                    diag_path.parent.mkdir(parents=True, exist_ok=True)
                    diag_path.write_text(json.dumps(ncdu_doc) + "\n")
                    _tee(f"Wrote diagnostic to {diag_path}\n", sinks)
            except Exception as e:
                _tee(f"diagnostic for {profile} failed: {e}\n", sinks)
                log(f"diagnostic for {profile} failed: {e}")

            total_bytes = sum(asize for _, asize, _ in items)

            if not ignore_added_size_limit and _exceeds_size_limit(
                config, profile, items, ncdu_doc, diag_path, sinks,
            ):
                results.append((profile, "size-limit exceeded; skipped", total_bytes, diag_path))
                continue

            if dry_run:
                # The dry-run pre-pass IS the dry-run; don't re-spawn restic.
                results.append((profile, "dry-run OK", total_bytes, diag_path))
                continue

            subcommands: list[str] = ["unlock", "backup"]
            if profile_mod.has_section(config, profile, "forget"):
                subcommands.append("forget")
            subcommands.append("check")

            profile_failure: tuple[str, int] | None = None
            for subcommand in subcommands:
                cmd, env_vars = profile_mod.build_command(config, profile, subcommand)
                rc = _stream(cmd, sinks, env={**os.environ, **env_vars})
                if rc != 0:
                    _tee(f"{subcommand} for {profile} exited with {rc}\n", sinks)
                    profile_failure = (subcommand, rc)
                    break  # skip remaining subcommands for this profile

            if profile_failure is None:
                results.append((profile, "OK", total_bytes, diag_path))
            else:
                sub, rc = profile_failure
                results.append((profile, f"{sub} failed (exit {rc})", total_bytes, diag_path))
                _notify(notify_on, f"Backup failed: {profile}",
                    f"`restic {sub}` exited with {rc}", urgent=True)

        _print_summary(sinks, results)

        def _is_success(status: str) -> bool:
            return (
                status == "OK"
                or status == "dry-run OK"
                or status.startswith("up-to-date")
            )

        ok_count = sum(1 for _, status, *_ in results if _is_success(status))
        failures = len(results) - ok_count
        backed_up = sum(
            1 for name, status, *_ in results
            if status in ("OK", "dry-run OK") and not name.startswith("fix-home/")
        )
        if failures:
            _tee(f"backup completed with {failures} failure(s)\n", sinks)
            _notify(notify_on, "Backup finished with failures",
                f"{ok_count} OK / {failures} failed", urgent=True)
            return 1
        # No failures. Fire a "finished" notification only if there was actual
        # backup work — silent for runs where everything was already up-to-date.
        if backed_up > 0:
            _notify(notify_on, "Backup finished",
                f"{ok_count} profile(s)/action(s) OK")
    return 0
