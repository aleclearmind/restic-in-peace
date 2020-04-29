#!/usr/bin/env python3

import argparse
import json
import re
import signal
import subprocess
import sys
import time

from loguru import logger

import utils

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

# WARN: boolean arguments must have action store_true, otherwise build_restic_args result will be incorrect
argparser = argparse.ArgumentParser(description="Restic wrapper implementing missing features needed by Rev.ng",
                                    epilog="Any other argument will get passed to restic as-is")
argparser.add_argument("command", help="Restic command")

# These options are specific of this tool and must not be passed to restic
argparser.add_argument("--added-size-limit", type=int, help="Maximim number of new bytes to backup. If restic counts more than this, the backup is aborted")
argparser.add_argument("--wifi-whitelist", action="extend", nargs="+",
                       help="Skip the backup if this parameter is provided and the computer is not connected to a network matching one of the provided regexes")
argparser.add_argument("--wifi-blacklist", action="extend", nargs="+",
                       help="Skip the backup if the computer is connected to a network matching one of the provided regexes")
argparser.add_argument("--skip-on-battery", action="store_true",
                       help="Skip the backup if the computer is battery powered")

# Restic options which we need to parse to invoke commands other than the original one
argparser.add_argument("--tag",
                       help="Only the latest snapshot having this tag will be considered as baseline. Supplying this option is highly recommended",
                       action="append")
argparser.add_argument("--repo", "-r", help="Restic repository")
argparser.add_argument("--password-file", "-p", help="Password file")
argparser.add_argument("--password-command", help="Password command")

# Global args which are get passed all invocations of restic
global_arguments = ["repo", "password_file", "password_command"]


def build_restic_command(command, args,
                         additional_argparse_arguments=None,
                         additional_unparsed_arguments=None,
                         force_json=True):
    additional_unparsed_arguments = additional_unparsed_arguments or []
    additional_argparse_arguments = additional_argparse_arguments or []

    restic_args = ["restic", command]

    for name in global_arguments + additional_argparse_arguments:
        val = vars(args).get(name, None)
        # Assumption: a False value is equivalent to not specifying a flag
        if val is False or val is None:
            continue

        restic_args.append("--" + name.replace("_", "-"))
        if isinstance(val, (str, int)):
            val = str(val)
        elif isinstance(val, list):
            val = " ".join(str(v) for v in val)
        elif val is True:
            continue
        else:
            error = f"Argument {name} is not string, int or list or True (actual type {type(val)})"
            wrapper_logs.error(error)
            raise TypeError(error)
        restic_args.append(val)

    restic_args += additional_unparsed_arguments

    if force_json and "--json" not in restic_args:
        restic_args.append("--json")

    return restic_args


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


def battery_ok(args):
    return not (args.skip_on_battery and utils.on_battery())


def network_ok(args):
    if args.wifi_blacklist:
        current_network = utils.get_wifi_network()
        if current_network is not None:
            for pattern in args.wifi_blacklist:
                if re.search(pattern, current_network):
                    wrapper_logs.info(f"Network {current_network} is blacklisted")
                    return False

    if args.wifi_whitelist:
        current_network = utils.get_wifi_network()
        if current_network is not None:
            for pattern in args.wifi_whitelist:
                if re.search(pattern, current_network):
                    wrapper_logs.info(f"Network {current_network} is whitelisted")
                    return True
            else:
                wrapper_logs.info(f"Network {current_network} is not in the whitelist")
                return False

    wrapper_logs.info(f"The computer default route does not appear to be a wireless network")
    return True


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
            # wrapper_logs.debug("Could not parse line as JSON")
            # wrapper_logs.debug(next_line)
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

                exit(return_codes["ABORT_TOO_MUCH_DATA"])

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
        exit(retcode)


def main(args, unparsed_args):
    if args.command == "backup":
        wrapper_logs.info("Backup command detected")

        if not battery_ok(args):
            wrapper_logs.error("The laptop is on battery power, skipping backup")
            exit(return_codes["SKIP_CAUSE_BATTERY"])

        if not network_ok(args):
            wrapper_logs.error("Skipping backup because of network conditions")
            exit(return_codes["SKIP_CAUSE_NETWORK"])

        run_backup(args, unparsed_args)

    else:
        restic_command = build_restic_command(args.command, args, additional_argparse_arguments=["tag"],
                                              additional_unparsed_arguments=unparsed_args, force_json=False)
        child = subprocess.Popen(restic_command)
        child.wait()


if __name__ == "__main__":
    arguments, remaining = argparser.parse_known_args()
    main(arguments, remaining)
