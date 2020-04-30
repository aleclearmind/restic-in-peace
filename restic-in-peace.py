#!/usr/bin/env python3

import argparse
import json
import signal
import subprocess
import sys
import time

from loguru import logger

import utils
from command import build_restic_command, run_command

logger.configure(handlers=[
    {"sink": sys.stdout, "format": "<level>{time}|{level}|{extra[logger_name]}|{message}</level>", "level": "INFO"}
])
wrapper_logs = logger.bind(logger_name="wrapper")
restic_logs = logger.bind(logger_name="wrapper")

return_codes = {
    "SKIP_CAUSE_BATTERY": -1,
    "SKIP_CAUSE_NETWORK": -2,
    "ABORT_TOO_MUCH_DATA": -3,
}

# WARN: boolean arguments must have action store_true, otherwise build_restic_command result will be incorrect
argparser = argparse.ArgumentParser(description="Restic wrapper implementing missing features needed by Rev.ng",
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

# Restic options which we need to parse to invoke commands other than the original one
argparser.add_argument("--tag", action="append",
                       help="Only the latest snapshot having this tag will be considered as baseline. Supplying this option is highly recommended")
argparser.add_argument("--repo", "-r", help="Restic repository")
argparser.add_argument("--password-file", "-p", help="Password file")
argparser.add_argument("--password-command", help="Password command")


def get_latest_snapshot_stats(args):
    get_latest_snapshot_command = build_restic_command("snapshots", args, additional_argparse_arguments=["tag"])
    process = utils.run_command(get_latest_snapshot_command)
    snapshots = json.loads(process.stdout)
    if not snapshots:
        return None, None
    snapshots.sort(key=lambda s: s["time"], reverse=True)
    latest_snapshot = snapshots[0]

    stats_command = build_restic_command("stats", args, additional_unparsed_arguments=[latest_snapshot["id"]])
    process = utils.run_command(stats_command)
    snapshot_stats = json.loads(process.stdout)
    return latest_snapshot, snapshot_stats


def run_backup(args, unparsed_args):
    latest_snapshot, latest_snapshot_stats = get_latest_snapshot_stats(args)
    if latest_snapshot is None or latest_snapshot_stats is None:
        latest_snapshot_size = 0
        latest_snapshot_id = "<NONE>"
        wrapper_logs.warning(
            f"Latest snapshot stats not found. It is normal if this is your first backup. Is the tag correct?")
    else:
        latest_snapshot_size = latest_snapshot_stats["total_size"]
        latest_snapshot_id = latest_snapshot["short_id"]
        wrapper_logs.info(f"Latest snapshot {latest_snapshot_id} has size {latest_snapshot_size}")

    backup_command = build_restic_command("backup", args, additional_argparse_arguments=["tag"],
                                          additional_unparsed_arguments=unparsed_args)

    process = subprocess.Popen(backup_command, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                               universal_newlines=True)
    scan_finished = False
    while True:
        next_line = process.stdout.readline()
        if next_line == "" and process.poll() is not None:
            break
        restic_logs.debug(next_line)

        try:
            parsed = json.loads(next_line)
        except json.JSONDecodeError:
            wrapper_logs.debug("Could not parse line as JSON")
            wrapper_logs.debug(next_line)
            continue

        if parsed["message_type"] == "status" and parsed.get("action", "") == "scan_finished":
            scan_finished = True
            total_files = parsed["total_files"]
            data_size = parsed["data_size"]
            duration = int(parsed["duration"])
            wrapper_logs.info(
                f"Finished filesystem scan in {duration}s, found {data_size} bytes to backup in {total_files} files")
            if args.added_size_limit and data_size - latest_snapshot_size > args.added_size_limit:
                wrapper_logs.critical(f"Backing up more than {args.added_size_limit} new bytes, aborting!")
                process.send_signal(signal.SIGINT)
                for _ in range(10):
                    if process.poll() is None:
                        time.sleep(1)
                    else:
                        break
                else:
                    wrapper_logs.warning("Restic did not gracefully terminate within 10 seconds, sending SIGKILL")
                    wrapper_logs.warning("You might need to run the unlock command")
                    process.kill()
                    process.wait()

                # TODO: maybe it would be better to raise an exception, so the return value would be unambiguous
                return return_codes["ABORT_TOO_MUCH_DATA"]

        elif parsed["message_type"] == "status" and scan_finished:
            percent_done = int(parsed.get("percent_done", 0) * 100)
            total_bytes = parsed.get("total_bytes", 0)
            total_files = parsed.get("total_files", 0)
            bytes_done = parsed.get("bytes_done", None)
            files_done = parsed.get("files_done", None)
            current_files = parsed.get("current_files", [])
            error_count = parsed.get("error_count", 0)
            wrapper_logs.info(f"Progress: {percent_done}% ({bytes_done}/{total_bytes} bytes, "
                              f"{files_done}/{total_files} files)")
            wrapper_logs.debug(f"Currently backing up: {', '.join(current_files)}")
            wrapper_logs.debug(f"Error count: {error_count}")

        elif parsed["message_type"] == "summary":
            files_new = parsed.get("files_new", "unknown")
            files_changed = parsed.get("files_changed", "unknown")
            files_unmodified = parsed.get("files_unmodified", "unknown")
            dirs_new = parsed.get("dirs_new", "unknown")
            dirs_changed = parsed.get("dirs_changed", "unknown")
            dirs_unmodified = parsed.get("dirs_unmodified", "unknown")
            data_added = parsed.get("data_added", "unknown")
            total_duration = parsed.get("total_duration", "unknown")
            snapshot_id = parsed.get("snapshot_id", "(unknown?)")
            wrapper_logs.info(f"Restic terminated in {total_duration} creating snapshot {snapshot_id}")
            wrapper_logs.info(f"{files_new}/{files_changed}/{files_unmodified} new/changed/unmodified files")
            wrapper_logs.info(f"{dirs_new}/{dirs_changed}/{dirs_unmodified} new/changed/unmodified directories")
            wrapper_logs.info(f"{data_added} bytes added to the backup")

    retcode = process.poll()
    if retcode != 0:
        wrapper_logs.error(f"Restic terminated with error code {retcode}")
    return retcode


def main(args, unparsed_args):
    if args.command == "backup":
        wrapper_logs.info("Backup command detected")

        if not utils.battery_ok(args.skip_on_battery):
            wrapper_logs.error("The laptop is on battery power, skipping backup")
            exit(return_codes["SKIP_CAUSE_BATTERY"])

        if not utils.network_ok(blacklist=args.wifi_blacklist, whitelist=args.wifi_whitelist):
            wrapper_logs.error("Skipping backup because of network conditions")
            exit(return_codes["SKIP_CAUSE_NETWORK"])

        utils.log_event_to_monitors("command_started", args.monitor_url,
                                    additional_data={"command": args.command, "tag": args.tag})
        returncode = run_backup(args, unparsed_args)
        event = "command_succeeded"
        additional_data = {"command": args.command, "tag": args.tag}
        if returncode:
            event = "command_failed"
            additional_data["returncode"] = returncode
        utils.log_event_to_monitors(event, args.monitor_url, additional_data=additional_data)

    else:
        restic_command = build_restic_command(args.command, args, additional_argparse_arguments=["tag"],
                                              additional_unparsed_arguments=unparsed_args, force_json=False)
        utils.log_event_to_monitors("command_started", args.monitor_url,
                                    additional_data={"command": args.command, "tag": args.tag})
        process = run_command(restic_command)
        returncode = process.returncode

        event = "command_succeeded"
        additional_data = {"command": args.command, "tag": args.tag}
        if returncode:
            event = "command_failed"
            additional_data["returncode"] = returncode
        utils.log_event_to_monitors(event, args.monitor_url, additional_data=additional_data)

    exit(returncode)


if __name__ == "__main__":
    arguments, remaining = argparser.parse_known_args()
    main(arguments, remaining)
