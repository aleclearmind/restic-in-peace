#!/usr/bin/env python3

import argparse
import json
import signal
import subprocess
import sys

from . import description
from . import utils
from .utils import logger

return_codes = {
    "SKIP_CAUSE_BATTERY": -1,
    "SKIP_CAUSE_NETWORK": -2,
    "ABORT_TOO_MUCH_DATA": -3,
    "INTERRUPTED": -4,
}

# WARN: boolean arguments must have action store_true, otherwise build_restic_command result will be incorrect
argparser = argparse.ArgumentParser(description=description,
                                    epilog="Any other argument will get passed to restic as-is")
argparser.add_argument("command", help="Restic command")

# These options are specific of this tool and must not be passed to restic
argparser.add_argument("--added-size-limit", type=int,
                       help="Maximim number of new bytes to backup. If restic counts more than this, the backup is aborted")
argparser.add_argument("--wifi-whitelist", action="append", default=[],
                       help="Skip the backup if this parameter is provided and the computer is not connected to a network matching one of the provided regexes. Can be speficied more than once")
argparser.add_argument("--wifi-blacklist", action="append", default=[],
                       help="Skip the backup if the computer is connected to a network matching one of the provided regexes. Can be specified more than once")
argparser.add_argument("--skip-on-battery", action="store_true",
                       help="Skip the backup if the computer is battery powered")
argparser.add_argument("--monitor-url", action="append", default=[],
                       help="Perform an HTTP POST request to this URL to report events. Can be specified more than once")
argparser.add_argument("--desktop-notifications", action="store_true",
                       help="Send desktop notification to any org.freedesktop.Notification compliant DBUS daemon")
argparser.add_argument("--tee-restic-logs",
                       help="Write restic output to this file. @CMD is substituted with the command, @FD with stdout or stderr")
argparser.add_argument("--loglevel", default="INFO", help="Log level (TRACE, DEBUG, INFO, WARNING, ERROR, CRITICAL)")

# Restic options which we need to parse to invoke commands other than the original one
argparser.add_argument("--tag", action="append",
                       help="Only the latest snapshot having this tag will be considered as baseline. Supplying this option is highly recommended")
argparser.add_argument("--repo", "-r", help="Restic repository")
argparser.add_argument("--password-file", "-p", help="Password file")
argparser.add_argument("--password-command", help="Password command")
argparser.add_argument("--verbose", "-v", nargs="?", help="Verbose output (passed to restic, for this wrapper use --loglevel)")


def get_latest_snapshot_stats(args):
    get_latest_snapshot_command = utils.build_restic_command("snapshots", args, additional_argparse_arguments=["tag"],
                                                             force_json=True)
    process = utils.run_command(get_latest_snapshot_command)
    try:
        snapshots = json.loads(process.stdout)
        if not snapshots:
            return None, None
    except json.JSONDecodeError:
        logger.error("Unexpected error while parsing restic output as JSON while getting latest snapshot stats")
        return None, None

    snapshots.sort(key=lambda s: s["time"], reverse=True)
    latest_snapshot = snapshots[0]

    stats_command = utils.build_restic_command("stats", args, additional_unparsed_arguments=[latest_snapshot["id"]],
                                               force_json=True)
    process = utils.run_command(stats_command)
    try:
        snapshot_stats = json.loads(process.stdout)
    except json.JSONDecodeError:
        logger.error("Unexpected error while parsing restic output as JSON while getting latest snapshot stats")
        return None, None
    return latest_snapshot, snapshot_stats


def run_backup(args, unparsed_args):
    latest_snapshot, latest_snapshot_stats = get_latest_snapshot_stats(args)
    if latest_snapshot is None or latest_snapshot_stats is None:
        latest_snapshot_size = 0
        latest_snapshot_id = "<NONE>"
        logger.warning(
            f"Latest snapshot stats not found. It is normal if this is your first backup. Is the tag correct?")
    else:
        latest_snapshot_size = latest_snapshot_stats["total_size"]
        latest_snapshot_id = latest_snapshot["short_id"]
        logger.info(f"Latest snapshot {latest_snapshot_id} has size {latest_snapshot_size}")

    backup_command = utils.build_restic_command("backup", args, additional_argparse_arguments=["tag"],
                                                additional_unparsed_arguments=unparsed_args, force_json=True,
                                                force_verbose=True)

    process = subprocess.Popen(backup_command, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                               universal_newlines=True)

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

            if parsed["message_type"] == "status" and parsed.get("action", "") == "scan_finished":
                scan_finished = True
                total_files = parsed["total_files"]
                data_size = parsed["data_size"]
                duration = int(parsed["duration"])
                logger.info(
                    f"Finished filesystem scan in {duration}s, found {data_size} bytes to backup in {total_files} files")
                data_left_amount = max(data_size - latest_snapshot_size, 0)
                if args.added_size_limit and data_left_amount > args.added_size_limit:
                    message = f"Attempting to backup {utils.to_si_units(data_left_amount)}, " \
                              f"the limit is {utils.to_si_units(args.added_size_limit)}, aborting!"
                    logger.critical(message)
                    process.send_signal(signal.SIGINT)
                    process.wait(timeout=10)
                    if process.poll() is None:
                        logger.warning("Restic did not gracefully terminate within 10 seconds, sending SIGKILL")
                        logger.warning("You might need to run the unlock command")
                        process.kill()
                        process.wait()

                    raise TooMuchDataException(message)

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

                message = f"Progress: {status} ({bytes_done}/{total_bytes} bytes, " \
                          f"{files_done}/{total_files} files, " \
                          f"{error_count} errors)"
                if utils.logging.ratelimit(topic="progress"):
                    logger.info(message)
                if current_files:
                    logger.debug(f"Currently backing up: {', '.join(current_files)}")

                if args.desktop_notifications and utils.logging.ratelimit(topic="progress-notification", threshold=0.1):
                    bytes_done_readable = utils.to_si_units(bytes_done)
                    total_bytes_readable = utils.to_si_units(total_bytes)
                    utils.show_notification(f"Backup in progress... ({status})",
                                            message=f"{files_done}/{total_files} files\n"
                                                    f"{bytes_done_readable}/{total_bytes_readable}",
                                            progress=percent_done)

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

                summary = "Backup succeeded"
                message = f"{log_message}\n"
                message += f"Added {utils.to_si_units(data_added)}"
                urgency = utils.notifications.URGENCY_NORMAL
                utils.show_notification(summary, message=message, urgency=urgency)

        retcode = process.poll()
        if retcode != 0:
            logger.error(f"Restic terminated with error code {retcode}")
        logger.log("RESTIC_ERR", process.stderr.read())
        return retcode


def main(args, unparsed_args):
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

        utils.log_event_to_monitors("command_started", args.monitor_url,
                                    additional_data={"command": args.command, "tag": args.tag})
        if args.desktop_notifications:
            utils.show_notification("Backup started", message=f"Backup with tag {', '.join(args.tag)}")

        additional_data = {"command": args.command, "tag": args.tag}
        try:
            restic_returncode = run_backup(args, unparsed_args)

            if restic_returncode:
                summary = "Backup failed"
                message = f"Backup with tag {', '.join(args.tag)} failed with code {restic_returncode}"
                urgency = utils.notifications.URGENCY_CRITICAL
                utils.show_notification(summary, message=message, urgency=urgency)

        except TooMuchDataException as e:
            summary = "Backup aborted"
            message = e.message
            urgency = utils.notifications.URGENCY_CRITICAL
            restic_returncode = return_codes["ABORT_TOO_MUCH_DATA"]
            additional_data["error"] = e.message
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
        restic_command = utils.build_restic_command(args.command, args, additional_argparse_arguments=["tag"],
                                                    additional_unparsed_arguments=unparsed_args)

        logger.debug(f"About to execute {restic_command}")

        utils.log_event_to_monitors("command_started", args.monitor_url,
                                    additional_data={"command": args.command, "tag": args.tag, "repo": args.repo})
        if args.desktop_notifications:
            summary = f"Restic {args.command} started"
            message = f"Restic {args.command} started on repo {args.repo}"
            if args.tag:
                message += f" with tag {', '.join(args.tag)}"
            utils.show_notification(summary, message=message)

        # Send realtime restic output to stdio as well as to loguru,
        # so it can also be redirected to a file with the --tee-restic-logs option
        stdout_wrapper = utils.logging.LoggingTextIOWrapper(sys.stdout, "RESTIC_OUT")
        stderr_wrapper = utils.logging.LoggingTextIOWrapper(sys.stderr, "RESTIC_ERR")
        process = subprocess.Popen(restic_command, stdout=stdout_wrapper, stderr=stderr_wrapper,
                                   universal_newlines=True)
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


class TooMuchDataException(Exception):
    def __init__(self, message, *args: object) -> None:
        self.message = message
        super().__init__(message, *args)


def entrypoint():
    arguments, remaining = argparser.parse_known_args()
    utils.logging.set_level(arguments.loglevel)
    main(arguments, remaining)
