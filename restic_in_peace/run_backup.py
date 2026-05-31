import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

import yaml

from . import profile as profile_mod
from .utils import logger


def _tee(text, sinks):
    for sink in sinks:
        sink.write(text)
        sink.flush()


def _stream(cmd, sinks):
    """Run `cmd`, line-streaming its merged stdout/stderr to each sink. Returns the exit code."""
    process = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )
    for line in process.stdout:
        _tee(line, sinks)
    return process.wait()


def _run_fix_home(config_path, sinks, sudo_user=None):
    """Verify that no fix-home action is pending for `sudo_user` (or the current user)."""
    prefix = ["sudo", "-Hu", sudo_user] if sudo_user else []
    cmd = prefix + ["restic-in-peace", "fix-home", "--strict", config_path]
    return _stream(cmd, sinks)


def run(config_path):
    config_path = os.path.abspath(config_path)
    try:
        with open(config_path) as f:
            config = yaml.safe_load(f) or {}
    except FileNotFoundError:
        logger.error(f"Config file not found: {config_path}")
        return 1
    except yaml.YAMLError as e:
        logger.error(f"Could not parse {config_path} as YAML: {e}")
        return 1

    try:
        log_dir = Path(config["run-backup"]["log-path"])
    except KeyError:
        logger.error(f"Missing 'run-backup'.'log-path' in {config_path}")
        return 1

    fix_homes_users = list(config.get("fix-homes", {}).keys())
    profiles = sorted(
        name
        for name, settings in config.get("profiles", {}).items()
        if isinstance(settings, dict) and settings.get("inherit") == "common"
    )

    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / datetime.now().strftime("%Y-%m-%d")
    current_user = os.environ.get("USER") or os.environ.get("LOGNAME")

    with log_path.open("a") as log_file:
        sinks = [sys.stdout, log_file]
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
            subcommands = ["unlock", "backup"]
            if profile_mod.has_section(config, profile, "forget"):
                subcommands.append("forget")
            subcommands.append("check")

            for subcommand in subcommands:
                cmd = ["restic-in-peace", "--config", config_path, "--name", profile, subcommand]
                rc = _stream(cmd, sinks)
                if rc != 0:
                    _tee(f"{subcommand} for {profile} exited with {rc}\n", sinks)
                    return rc

    return 0
