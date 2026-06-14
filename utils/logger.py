"""
UTIL: Logger
PURPOSE: Structured logging to file + stdout
"""

import logging
import sys
from utils.config import LOG_LEVEL


def get_logger(name: str) -> logging.Logger:
    logger = logging.getLogger(name)
    if logger.handlers:
        return logger

    logger.setLevel(getattr(logging, LOG_LEVEL.upper(), logging.INFO))

    formatter = logging.Formatter(
        "%(asctime)s | %(name)s | %(levelname)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    stdout_handler = logging.StreamHandler(sys.stdout)
    stdout_handler.setFormatter(formatter)
    logger.addHandler(stdout_handler)

    file_handler = logging.FileHandler("./logs/automation.log", encoding="utf-8")
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    return logger


def log_info(msg: str):
    get_logger("newsbot").info(msg)


def log_error(msg: str):
    get_logger("newsbot").error(msg)


def log_debug(msg: str):
    get_logger("newsbot").debug(msg)
