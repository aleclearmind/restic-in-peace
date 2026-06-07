import subprocess

from .logging import logger


def run_command(args, shell=False):
    logger.debug(f"About to execute {args}")
    process = subprocess.run(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE, universal_newlines=True, shell=shell)
    return process
