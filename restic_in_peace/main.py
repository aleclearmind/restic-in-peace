#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import shlex
from typing import Any

from . import description
from . import utils
from .utils import human_numbers
from .utils import logger

return_codes: dict[str, int] = {
    "SKIP_CAUSE_BATTERY": -1,
    "SKIP_CAUSE_NETWORK": -2,
    "INTERRUPTED": -4,
}

# WARN: boolean arguments must have action store_true, otherwise build_restic_command result will be incorrect
def _build_parsers() -> tuple[argparse.ArgumentParser, argparse.ArgumentParser]:
    """Construct the rip argument parser plus the lightweight pre-parser that
    extracts -c/--config and -n/--name before the main parser runs.

    Returned as (main, pre)."""
    main = argparse.ArgumentParser(prog="restic-in-peace", description=description)
    # --config/--name are intercepted before argparser runs (see entrypoint), but
    # listed here so they appear in --help.
    main.add_argument("-c", "--config", metavar="FILE", help="path to rip.yaml (use with --name)")
    main.add_argument("-n", "--name", metavar="PROFILE", help="profile name within --config")
    main.add_argument("--loglevel", default="INFO",
        help="Log level (TRACE, DEBUG, INFO, WARNING, ERROR, CRITICAL)")

    subparsers = main.add_subparsers(dest="command", required=True, metavar="<subcommand>")

    restic = subparsers.add_parser("restic",
        help="run a restic command; `backup` goes through rip's gates and notifications")
    restic.add_argument("restic_subcommand",
        help="restic subcommand (backup, snapshots, restore, mount, ...)")
    restic.add_argument("--added-size-limit", type=human_numbers.parse,
        help="abort backup if restic would add more than this many bytes")
    restic.add_argument("--wifi-whitelist", action="append", default=[],
        help="skip backup unless the active wifi matches one of these regexes (repeatable)")
    restic.add_argument("--wifi-blacklist", action="append", default=[],
        help="skip backup if the active wifi matches one of these regexes (repeatable)")
    restic.add_argument("--skip-on-battery", action="store_true", dest="skip_on_battery",
        help="skip the backup if the computer is on battery")
    restic.add_argument("--no-skip-on-battery", action="store_false", dest="skip_on_battery",
        help="force the backup even if the computer is on battery")
    restic.add_argument("--monitor-url", action="append", default=[],
        help="POST event JSON to this URL on backup transitions (repeatable)")
    restic.add_argument("--desktop-notifications", action="store_true",
        help="send notify-send notifications on backup transitions")
    restic.add_argument("--tee-restic-logs", metavar="FILE",
        help="duplicate restic's output to this file (@CMD/@FD substituted)")
    restic.add_argument("--tag", action="append",
        help="restic tag (also used as the size-limit baseline filter; highly recommended)")
    restic.add_argument("-r", "--repo", help="restic repository")
    restic.add_argument("-p", "--password-file", help=argparse.SUPPRESS)
    restic.add_argument("--password-command", help=argparse.SUPPRESS)
    restic.add_argument("-v", "--verbose", nargs="?", metavar="LEVEL",
        help="verbose output (forwarded to restic)")
    restic.add_argument("--dry-run", action="store_true", dest="dry_run",
        help="forward --dry-run to restic (supported by backup/forget/prune)")

    fix_home = subparsers.add_parser("fix-home",
        help="emit a bash script (or --strict-check) for fix-homes/$USER dotfile symlinks")
    fix_home.add_argument("--strict", action="store_true",
        help="fail non-zero if any move/link would be needed; emit no bash")
    fix_home.add_argument("config", nargs="?", default="rip.yaml",
        help="config file (default: rip.yaml in CWD)")

    run_backup_p = subparsers.add_parser("run-backup",
        help="orchestrate fix-home + unlock + backup + forget + check for every "
             "profile inheriting from common; write per-profile ncdu diagnostic")
    run_backup_p.add_argument("--dry-run", action="store_true", dest="dry_run",
        help="skip unlock and check, pass --dry-run to backup and forget")
    run_backup_p.add_argument("--log-path", dest="log_path", metavar="DIR",
        help="directory where the dated <run> subdir goes (overrides run-backup.log-path)")
    run_backup_p.add_argument("--only", action="append", default=[], metavar="PROFILE",
        help="only back up profiles with these names; can be repeated")
    run_backup_p.add_argument("--ignore-skip-on-battery", action="store_true",
        dest="ignore_skip_on_battery",
        help="bypass the battery gate (run even on battery power)")
    run_backup_p.add_argument("--ignore-added-size-limit", action="store_true",
        dest="ignore_added_size_limit",
        help="bypass the added-size-limit gate per profile")
    run_backup_p.add_argument("--ignore-wifi-whitelist", action="store_true",
        dest="ignore_wifi_whitelist",
        help="bypass the wifi-whitelist gate (wifi-blacklist still applies)")
    run_backup_p.add_argument("config", help="config file")

    collect = subparsers.add_parser("collect-non-backuped-files",
        help="list files present on disk that no common-inheriting profile would back up")
    collect.add_argument("config", help="config file")
    collect.add_argument("output_dir", help="output directory")

    pre = argparse.ArgumentParser(add_help=False)
    pre.add_argument("-c", "--config")
    pre.add_argument("-n", "--name")

    return main, pre


def run_backup(args: argparse.Namespace, unparsed_args: list[str]) -> int | None:
    backup_command = utils.build_restic_command(
        "backup",
        args,
        additional_argparse_arguments=["tag", "dry_run"],
        additional_unparsed_arguments=unparsed_args,
        force_json=True,
        force_verbose=True,
    )

    logger.info(shlex.join(backup_command))

    process = subprocess.Popen(backup_command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, universal_newlines=True)
    assert process.stdout is not None and process.stderr is not None

    with utils.command.EnsureGracefulExit(process):
        scan_finished = False
        while True:
            next_line = process.stdout.readline()
            if next_line == "" and process.poll() is not None:
                break
            logger.log("RESTIC_OUT", next_line)

            try:
                parsed = json.loads(next_line)
            except json.JSONDecodeError:
                logger.debug("Could not parse line as JSON")
                continue

            if parsed["message_type"] in ("status", "verbose_status") and parsed.get("action", "") == "scan_finished":
                scan_finished = True
                total_files = parsed["total_files"]
                data_size = parsed["data_size"]
                duration = int(parsed["duration"])
                logger.info(
                    f"Finished filesystem scan in {duration}s, found {data_size} bytes to backup in {total_files} files"
                )

            elif parsed["message_type"] == "status":
                total_bytes = parsed.get("total_bytes", 0)
                total_files = parsed.get("total_files", 0)
                bytes_done = parsed.get("bytes_done", 0)
                files_done = parsed.get("files_done", 0)
                current_files = parsed.get("current_files", [])
                error_count = parsed.get("error_count", 0)

                if scan_finished:
                    percent_done = int(parsed.get("percent_done", 0) * 100)
                    status = f"{percent_done}%"
                else:
                    if total_bytes:
                        percent_done = int(bytes_done / total_bytes * 100)
                    else:
                        percent_done = 0
                    status = f"{percent_done}%, scanning"

                message = (
                    f"Progress: {status} ({bytes_done}/{total_bytes} bytes, "
                    f"{files_done}/{total_files} files, "
                    f"{error_count} errors)"
                )
                if utils.logging.ratelimit(topic="progress"):
                    logger.info(message)
                if current_files:
                    logger.debug(f"Currently backing up: {', '.join(current_files)}")

                if args.desktop_notifications and utils.logging.ratelimit(topic="progress-notification", threshold=0.1):
                    bytes_done_readable = human_numbers.to_si(bytes_done)
                    total_bytes_readable = human_numbers.to_si(total_bytes)
                    utils.show_notification(
                        f"Backup in progress... ({status})",
                        message=f"{files_done}/{total_files} files\n" f"{bytes_done_readable}/{total_bytes_readable}",
                        progress=percent_done,
                    )

            elif parsed["message_type"] == "summary":
                files_new = parsed.get("files_new", 0)
                files_changed = parsed.get("files_changed", 0)
                files_unmodified = parsed.get("files_unmodified", 0)
                dirs_new = parsed.get("dirs_new", 0)
                dirs_changed = parsed.get("dirs_changed", 0)
                dirs_unmodified = parsed.get("dirs_unmodified", 0)
                data_added = parsed.get("data_added", 0)
                total_duration = parsed.get("total_duration", "unknown")
                snapshot_id = parsed.get("snapshot_id", "(unknown?)")

                if args.tag:
                    tag_msg = f" tagged {', '.join(args.tag)}"
                else:
                    tag_msg = ""
                log_message = f"Created snapshot {snapshot_id}{tag_msg} in {int(total_duration)} seconds"
                logger.info(log_message)
                logger.info(f"{files_new}/{files_changed}/{files_unmodified} new/changed/unmodified files")
                logger.info(f"{dirs_new}/{dirs_changed}/{dirs_unmodified} new/changed/unmodified directories")
                logger.info(f"{data_added} bytes added to the backup")

                summary = "Backup finished"
                message = f"{log_message}\n"
                message += f"Added {human_numbers.to_si(data_added)}"
                urgency = utils.notifications.URGENCY_NORMAL
                if args.desktop_notifications:
                    utils.show_notification(summary, message=message, urgency=urgency)

        retcode = process.poll()
        if retcode != 0:
            logger.error(f"Restic terminated with error code {retcode}")
        logger.log("RESTIC_ERR", process.stderr.read())
        return retcode


def main(args: argparse.Namespace, unparsed_args: list[str]) -> None:
    if args.command == "fix-home":
        from .fix_home import run as fix_home_run
        exit(fix_home_run(args.config, strict=args.strict))

    if args.command == "run-backup":
        from .run_backup import run as run_backup_run
        exit(run_backup_run(
            args.config,
            dry_run=args.dry_run,
            log_path=args.log_path,
            only=args.only,
            ignore_skip_on_battery=args.ignore_skip_on_battery,
            ignore_added_size_limit=args.ignore_added_size_limit,
            ignore_wifi_whitelist=args.ignore_wifi_whitelist,
        ))

    if args.command == "collect-non-backuped-files":
        from .collect import run as collect_run
        exit(collect_run(args.config, args.output_dir))

    # Everything below this point assumes args.command is the restic subcommand
    # (entrypoint moved restic's positional subcommand into args.command).
    if args.tee_restic_logs:
        destination = args.tee_restic_logs.replace("@CMD", args.command)
        stdout_destination = destination.replace("@FD", "stdout")
        stderr_destination = destination.replace("@FD", "stderr")
        logger.info(f"Appending restic stdout to {stdout_destination}, stderr to {stderr_destination}")
        utils.logging.send_restic_output_to_file(stdout_destination)
        utils.logging.send_restic_errors_to_file(stderr_destination)

    if args.command == "backup":
        if not utils.battery_ok(args.skip_on_battery):
            logger.error("The laptop is on battery power, skipping backup")
            exit(return_codes["SKIP_CAUSE_BATTERY"])

        if not utils.network_ok(blacklist=args.wifi_blacklist, whitelist=args.wifi_whitelist):
            logger.error("Skipping backup because of network conditions")
            exit(return_codes["SKIP_CAUSE_NETWORK"])

        utils.log_event_to_monitors(
            "command_started", args.monitor_url, additional_data={"command": args.command, "tag": args.tag}
        )
        if args.desktop_notifications:
            utils.show_notification("Backup started", message=f"Backup with tag {', '.join(args.tag)}")

        additional_data = {"command": args.command, "tag": args.tag}
        try:
            restic_returncode = run_backup(args, unparsed_args)

            if restic_returncode:
                if restic_returncode == 3:
                    summary = "Backup succeeded with errors"
                    message = f"Backup with tag {', '.join(args.tag)} finished but some files could not be read"
                    urgency = utils.notifications.URGENCY_NORMAL
                else:
                    summary = "Backup failed"
                    message = f"Backup with tag {', '.join(args.tag)} failed with code {restic_returncode}"
                    urgency = utils.notifications.URGENCY_CRITICAL

        except KeyboardInterrupt:
            logger.error("Backup aborted due to SIGINT")
            summary = "Backup aborted"
            message = "Backup stopped by the user (SIGINT)"
            urgency = utils.notifications.URGENCY_NORMAL
            restic_returncode = return_codes["INTERRUPTED"]
            additional_data["error"] = "Program received SIGINT"

        event = "command_succeeded" if restic_returncode == 0 else "command_failed"
        additional_data["returncode"] = restic_returncode
        utils.log_event_to_monitors(event, args.monitor_url, additional_data=additional_data)

        if restic_returncode and args.desktop_notifications:
            utils.show_notification(summary, message=message, urgency=urgency)

    else:
        if args.command == "raw-backup":
            args.command = "backup"

        restic_command = utils.build_restic_command(
            args.command, args,
            additional_argparse_arguments=["tag", "dry_run"],
            additional_unparsed_arguments=unparsed_args,
        )

        logger.info(f"About to execute {shlex.join(restic_command)}")

        utils.log_event_to_monitors(
            "command_started",
            args.monitor_url,
            additional_data={"command": args.command, "tag": args.tag, "repo": args.repo},
        )
        if args.desktop_notifications:
            summary = f"Restic {args.command} started"
            message = f"Restic {args.command} started on repo {args.repo}"
            if args.tag:
                message += f" with tag {', '.join(args.tag)}"
            utils.show_notification(summary, message=message)

        # Send realtime restic output to stdio as well as to loguru,
        # so it can also be redirected to a file with the --tee-restic-logs option
        stdout_wrapper = utils.logging.LoggingTextIOWrapper(sys.stdout, "RESTIC_OUT")  # type: ignore[arg-type]
        stderr_wrapper = utils.logging.LoggingTextIOWrapper(sys.stderr, "RESTIC_ERR")  # type: ignore[arg-type]
        process = subprocess.Popen(  # type: ignore[call-overload]
            restic_command, stdout=stdout_wrapper, stderr=stderr_wrapper, universal_newlines=True
        )
        with utils.command.EnsureGracefulExit(process):
            process.wait()
        stdout_wrapper.close()
        stderr_wrapper.close()

        restic_returncode = process.returncode

        event = "command_succeeded"
        additional_data = {"command": args.command, "tag": args.tag, "repo": args.repo}
        if restic_returncode:
            event = "command_failed"
            additional_data["returncode"] = restic_returncode
        utils.log_event_to_monitors(event, args.monitor_url, additional_data=additional_data)

        if args.desktop_notifications:
            if restic_returncode:
                summary = f"Restic {args.command} failed"
                message = f"Restic {args.command} failed with code {restic_returncode} on repo {args.repo}"
                urgency = utils.notifications.URGENCY_CRITICAL
            else:
                summary = f"Restic {args.command} succeeded"
                message = f"Restic {args.command} succeeded on repo {args.repo}"
                urgency = utils.notifications.URGENCY_NORMAL
            if args.tag:
                message += f" with tag {', '.join(args.tag)}"
            utils.show_notification(summary, message=message, urgency=urgency)

    exit(restic_returncode)




def entrypoint() -> None:
    argparser, pre_parser = _build_parsers()
    pre_args, argv = pre_parser.parse_known_args(sys.argv[1:])
    config_path, profile_name = pre_args.config, pre_args.name

    forward_to_restic: list[str] = []

    if config_path or profile_name:
        if not (config_path and profile_name):
            sys.stderr.write("--config and --name must be supplied together\n")
            sys.exit(2)
        if not argv or argv[0] != "restic":
            sys.stderr.write("--config/--name require the `restic` subcommand\n")
            sys.exit(2)
        if len(argv) < 2:
            sys.stderr.write("`restic` requires a subcommand\n")
            sys.exit(2)

        restic_subcmd = argv[1]
        cli_rest = argv[2:]

        from . import profile as profile_mod
        try:
            config = profile_mod.load_config(config_path)
            settings, env = profile_mod.resolve(config, profile_name, restic_subcmd)
        except (KeyError, ValueError, profile_mod.ConfigError) as e:
            sys.stderr.write(f"{e}\n")
            sys.exit(1)

        flags, positionals = profile_mod.to_argv(settings, restic_subcmd)
        for k, v in env.items():
            os.environ.setdefault(k, str(v))

        # CLI sanity check: parse just the user-typed portion. If argparse
        # leaves anything over, the user typed an unknown flag/positional we
        # would otherwise silently forward to restic — refuse instead.
        _, cli_extras = argparser.parse_known_args(["restic", restic_subcmd, *cli_rest])
        if cli_extras:
            sys.stderr.write(f"unknown argument(s) for restic: {' '.join(cli_extras)}\n")
            sys.exit(2)

        # Full parse: profile flags + CLI flags + profile positionals. The
        # `remaining` here is purely profile-derived (CLI was just verified
        # to be clean) so it's safe to forward to restic.
        arguments, remaining = argparser.parse_known_args(
            ["restic", restic_subcmd, *flags, *cli_rest, *positionals],
        )
        forward_to_restic = remaining
    else:
        arguments, remaining = argparser.parse_known_args(argv)
        if remaining:
            sys.stderr.write(
                f"unknown argument(s) for {arguments.command}: {' '.join(remaining)}\n"
            )
            sys.exit(2)

    utils.logging.set_level(arguments.loglevel)

    # Promote the restic subcommand into args.command so the existing dispatch
    # (backup pipeline vs passthrough) keeps working.
    if arguments.command == "restic":
        arguments.command = arguments.restic_subcommand

    main(arguments, forward_to_restic)
