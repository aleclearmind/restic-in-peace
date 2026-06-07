#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import sys

from . import description
from . import profile as profile_mod
from .utils import log


def _build_parser() -> argparse.ArgumentParser:
    main = argparse.ArgumentParser(prog="rip", description=description)
    main.add_argument("-c", "--config", default="rip.yml", metavar="FILE",
        help="path to the rip config file (default: rip.yml in CWD)")

    subparsers = main.add_subparsers(dest="command", required=True, metavar="<subcommand>")

    restic = subparsers.add_parser("restic",
        help="run a restic subcommand using a profile's configuration")
    restic_subparsers = restic.add_subparsers(
        dest="restic_subcommand", required=True, metavar="<restic-subcommand>",
    )
    for subcmd in sorted(profile_mod.COMMAND_SECTIONS):
        sp = restic_subparsers.add_parser(subcmd,
            help=f"run `restic {subcmd}` with the named profile's settings")
        sp.add_argument("profile",
            help="profile name within --config")

    backup_p = subparsers.add_parser("backup",
        help="orchestrate fix-home + unlock + backup + forget + check for every "
             "profile inheriting from common; write per-profile ncdu diagnostic")
    backup_p.add_argument("--dry-run", action="store_true", dest="dry_run",
        help="skip unlock and check, pass --dry-run to backup and forget")
    backup_p.add_argument("--log-path", dest="log_path", metavar="DIR",
        help="directory where the dated <run> subdir goes (overrides log-path in config)")
    backup_p.add_argument("--only", action="append", default=[], metavar="PROFILE",
        help="only back up profiles with these names; can be repeated")
    backup_p.add_argument("--ignore-skip-on-battery", action="store_true",
        dest="ignore_skip_on_battery",
        help="bypass the battery gate (run even on battery power)")
    backup_p.add_argument("--ignore-added-size-limit", action="store_true",
        dest="ignore_added_size_limit",
        help="bypass the added-size-limit gate per profile")
    backup_p.add_argument("--ignore-wifi-whitelist", action="store_true",
        dest="ignore_wifi_whitelist",
        help="bypass the wifi-whitelist gate (wifi-blacklist still applies)")

    fix_home = subparsers.add_parser("fix-home",
        help="emit a bash script (or --strict-check) for fix-homes/$USER dotfile symlinks")
    fix_home.add_argument("--strict", action="store_true",
        help="fail non-zero if any move/link would be needed; emit no bash")

    collect = subparsers.add_parser("collect-non-backuped-files",
        help="list files present on disk that no common-inheriting profile would back up")
    collect.add_argument("output_dir", help="output directory")

    return main


def main(arguments: argparse.Namespace, restic_extras: list[str]) -> int:
    config_path = os.path.abspath(arguments.config)

    if arguments.command == "fix-home":
        from .fix_home import run as fix_home_run
        return fix_home_run(config_path, strict=arguments.strict)

    if arguments.command == "backup":
        from .backup import run as backup_run
        return backup_run(
            config_path,
            dry_run=arguments.dry_run,
            log_path=arguments.log_path,
            only=arguments.only,
            ignore_skip_on_battery=arguments.ignore_skip_on_battery,
            ignore_added_size_limit=arguments.ignore_added_size_limit,
            ignore_wifi_whitelist=arguments.ignore_wifi_whitelist,
        )

    if arguments.command == "collect-non-backuped-files":
        from .collect import run as collect_run
        return collect_run(config_path, arguments.output_dir)

    # arguments.command == "restic": dispatch to the named restic subcommand
    # under the named profile.
    try:
        config = profile_mod.load_config(config_path)
        argv, env = profile_mod.build_command(
            config, arguments.profile, arguments.restic_subcommand,
        )
    except (KeyError, ValueError, profile_mod.ConfigError) as e:
        log(str(e))
        return 1

    argv.extend(restic_extras)
    proc_env = {**os.environ, **env}
    os.execvpe(argv[0], argv, proc_env)


def entrypoint() -> None:
    parser = _build_parser()
    arguments, extras = parser.parse_known_args()

    if arguments.command != "restic" and extras:
        parser.error(f"unknown argument(s): {' '.join(extras)}")

    sys.exit(main(arguments, extras))
