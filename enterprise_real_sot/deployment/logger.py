import logging
import sys

def get_logger(name: str = "NACDeployment") -> logging.Logger:
    """
    Returns a configured thread-safe Logger instance.
    """
    # Fetch or create a named logger. Reusing names returns the same logger instance across modules.
    logger = logging.getLogger(name)
    # Check if handlers already exist to prevent adding duplicate handlers and printing duplicate log lines.
    if not logger.handlers:
        # Set overall minimum log level to INFO so DEBUG messages are filtered out by default.
        logger.setLevel(logging.INFO)
        # Direct log output to standard output console (stdout).
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setLevel(logging.INFO)
        # Format logs with timestamp, logger module name, severity level, and log message.
        formatter = logging.Formatter(
            fmt="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S"
        )
        console_handler.setFormatter(formatter)
        # Attach configured stream handler to the logger instance.
        logger.addHandler(console_handler)
    return logger


