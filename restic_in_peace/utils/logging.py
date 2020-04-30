import sys

from loguru import logger

levels = {
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


global_filter = MinimumLevelFilter("INFO")

logger.configure(handlers=[
    {"sink": sys.stdout, "filter": global_filter,
     "format": "<level>{time}|{level}|{module}|{message}</level>", "level": 0}
])
logger.level("RESTIC_OUT", no=logger.level("DEBUG").no, color=logger.level("DEBUG").color)
logger.level("RESTIC_ERR", no=logger.level("DEBUG").no, color=logger.level("DEBUG").color)


def set_level(level):
    try:
        level = int(level)
    except ValueError:
        pass
    global_filter.level = level


def send_restic_output_to_file(file):
    restic_out_only_filter = ExactLevelFilter("RESTIC_OUT")
    logger.add(file, level=0, filter=restic_out_only_filter, format="{message}")


def send_restic_errors_to_file(file):
    restic_err_only_filter = ExactLevelFilter("RESTIC_ERR")
    logger.add(file, level=0, filter=restic_err_only_filter, format="{message}")
