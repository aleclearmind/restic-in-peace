import signal
import subprocess

from .logging import logger


def run_command(args, shell=False):
    logger.debug(f"About to execute {args}")
    process = subprocess.run(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE, universal_newlines=True, shell=shell)
    return process


def build_restic_command(
    command,
    args_from_argparse,
    additional_argparse_arguments=None,
    additional_unparsed_arguments=None,
    force_json=False,
    force_verbose=False,
):
    additional_unparsed_arguments = additional_unparsed_arguments or []
    additional_argparse_arguments = additional_argparse_arguments or []

    # Global args_from_argparse which are get passed all invocations of restic
    global_arguments = ["repo", "password_file", "password_command", "verbose"]

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
            logger.error(error)
            raise TypeError(error)
        restic_args.append(val)

    restic_args += additional_unparsed_arguments

    if force_json and "--json" not in restic_args:
        restic_args.append("--json")

    if force_verbose and "--verbose" not in restic_args:
        restic_args.append("--verbose")
        restic_args.append("2")

    return restic_args


class EnsureGracefulExit:
    def __init__(self, subproc, timeout=10):
        self.subprocess: subprocess.Popen = subproc
        self.timeout = timeout

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self.subprocess.poll():
            return

        # TODO: should we terminate the subprocess with other signals/exceptions?
        if exc_type is KeyboardInterrupt:
            self.subprocess.send_signal(signal.SIGINT)
            self.subprocess.wait(timeout=self.timeout)
            if self.subprocess.poll() is None:
                self.subprocess.kill()
                self.subprocess.wait()
            return True
