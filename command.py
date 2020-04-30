import subprocess
import sys

from loguru import logger

logger.configure(handlers=[
    {"sink": sys.stdout, "format": "<level>{time}|{level}|{extra[logger_name]}|{message}</level>", "level": "INFO"}
])
log = logger.bind(logger_name="command")


def run_command(args, shell=False):
    log.debug(f"About to execute {args}")
    process = subprocess.run(args, capture_output=True, universal_newlines=True, shell=shell)
    return process


def build_restic_command(command, args_from_argparse,
                         additional_argparse_arguments=None,
                         additional_unparsed_arguments=None,
                         force_json=True):
    additional_unparsed_arguments = additional_unparsed_arguments or []
    additional_argparse_arguments = additional_argparse_arguments or []

    # Global args_from_argparse which are get passed all invocations of restic
    global_arguments = ["repo", "password_file", "password_command"]

    restic_args = ["restic", command]

    for name in global_arguments + additional_argparse_arguments:
        val = vars(args_from_argparse).get(name, None)
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
            log.error(error)
            raise TypeError(error)
        restic_args.append(val)

    restic_args += additional_unparsed_arguments

    if force_json and "--json" not in restic_args:
        restic_args.append("--json")

    return restic_args
