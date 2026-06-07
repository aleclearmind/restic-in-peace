import sys


def log(message: object) -> None:
    print(message, file=sys.stderr, flush=True)
