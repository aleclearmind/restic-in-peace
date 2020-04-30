import sys

from loguru import logger

logger.configure(handlers=[
    {"sink": sys.stdout, "format": "<level>{time}|{level}|{module}|{message}</level>", "level": "INFO"}
])
