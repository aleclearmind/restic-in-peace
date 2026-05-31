import io
import os
import sys
import threading
import time
from typing import List

from loguru import logger

levels = {
    "TRACE": 5,
    "DEBUG": 10,
    "RESTIC": 10,
    "INFO": 20,
    "WARNING": 30,
    "ERROR": 40,
    "CRITICAl": 50,
}


class MinimumLevelFilter:
    def __init__(self, level="INFO"):
        self.level = level

    def __call__(self, record):
        record_level = record["level"].no
        if isinstance(self.level, int):
            return record_level >= self.level
        else:
            return record_level >= levels.get(self.level, 20)


class ExactLevelFilter:
    def __init__(self, level="INFO"):
        self.level = level

    def __call__(self, record):
        if isinstance(self.level, int):
            return record["level"].no == self.level
        else:
            return record["level"].name == self.level


class LoggingTextIOWrapper:
    def __init__(self, wrapped: io.TextIOBase, loglevel, close_wrapped_object=False, encoding="utf-8"):
        self.wrapped: io.TextIOBase = wrapped
        self.loglevel = loglevel
        self.pipe_r, self.pipe_w = os.pipe()
        self.thread = threading.Thread(target=self.mirror)
        self.thread.start()
        self.closed = False
        self.close_wrapped_object = close_wrapped_object
        self.encoding = encoding

    def mirror(self):
        data = os.read(self.pipe_r, 1024 * 1024)
        while not self.closed or data:
            if data:
                logger.log(self.loglevel, data.decode(self.encoding))
                os.write(self.wrapped.fileno(), data)
            # Windows does not support select() on pipes
            time.sleep(0.1)
            data = os.read(self.pipe_r, 1024 * 1024)

    def write(self, s: str) -> int:
        logger.log(self.loglevel, s)
        return self.wrapped.write(s)

    def writelines(self, lines: List[str]) -> None:
        for line in lines:
            logger.log(self.loglevel, line)
        return self.wrapped.writelines(lines)

    def fileno(self) -> int:
        return self.pipe_w

    def close(self) -> None:
        os.close(self.pipe_w)
        self.closed = True
        self.thread.join()
        if self.close_wrapped_object:
            self.wrapped.close()
        os.close(self.pipe_r)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
        return True

    def readable(self):
        return False

    def writable(self):
        return not self.closed and self.wrapped.writable()


def set_level(level):
    try:
        level = int(level)
    except ValueError:
        pass
    global_filter.level = level


def ratelimit(topic="", threshold=1, update=True):
    last_message_timestamp = topic_timestamps.get(topic, 0)
    ratelimit_ok = last_message_timestamp + threshold < time.time()
    if ratelimit_ok and update:
        topic_timestamps[topic] = time.time()
    return ratelimit_ok


def send_log_to_file(file, filter=None, level=0, format="{message}", truncate=True):
    if truncate and os.path.exists(file):
        try:
            os.truncate(file, 0)
        except:
            pass
    logger.add(file, level=level, filter=filter, format=format)


def send_restic_output_to_file(file, truncate=True):
    send_log_to_file(file, filter=restic_out_only_filter, truncate=truncate)


def send_restic_errors_to_file(file, truncate=True):
    send_log_to_file(file, filter=restic_err_only_filter, truncate=truncate)


topic_timestamps: dict[str, float] = {}
global_filter = MinimumLevelFilter("INFO")
restic_out_only_filter = ExactLevelFilter("RESTIC_OUT")
restic_err_only_filter = ExactLevelFilter("RESTIC_ERR")

logger.level("RESTIC_OUT", no=logger.level("TRACE").no, color=logger.level("TRACE").color)
logger.level("RESTIC_ERR", no=logger.level("TRACE").no, color=logger.level("TRACE").color)

logger.configure(
    handlers=[
        {
            "sink": sys.stdout,
            "level": 0,
            "format": "<level>{time}|{level}|{module}|{message}</level>",
            "filter": global_filter,
        }
    ]
)
