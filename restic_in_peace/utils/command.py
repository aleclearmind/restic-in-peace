import subprocess


def run_command(args, shell=False):
    return subprocess.run(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE, universal_newlines=True, shell=shell)
