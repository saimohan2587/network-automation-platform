"""Structured logging module for device_migration package."""

import logging
import sys

_LOGGERS = {}


def get_logger(name: str = "DeviceMigration") -> logging.Logger:
    """Return a configured logger with console handler."""
    if name in _LOGGERS:
        return _LOGGERS[name]

    logger = logging.getLogger(f"DeviceMigration.{name}")
    logger.setLevel(logging.INFO)

    if not logger.handlers:
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setLevel(logging.INFO)
        formatter = logging.Formatter(
            "%(asctime)s - %(name)s - %(levelname)s - %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S"
        )
        console_handler.setFormatter(formatter)
        logger.addHandler(console_handler)

    _LOGGERS[name] = logger
    return logger
