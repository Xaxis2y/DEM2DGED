# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (c) 2026 Eui Soo SON

import logging
import sys
from typing import Optional


class ColoredFormatter(logging.Formatter):
    """Custom formatter with colored output (optional, based on terminal support)."""

    COLORS = {
        'DEBUG': '\033[36m',    # Cyan
        'INFO': '\033[32m',     # Green
        'WARNING': '\033[33m',  # Yellow
        'ERROR': '\033[31m',    # Red
        'CRITICAL': '\033[35m', # Magenta
        'RESET': '\033[0m',
    }

    def __init__(self, use_color: bool = True, fmt: Optional[str] = None) -> None:
        """Initialize formatter with optional color support.

        v0.39: ``fmt`` is now passed through to logging.Formatter's
        constructor. Previously setup_logging() built the formatter with no
        format and then assigned ``formatter._fmt`` afterwards -- but
        logging.Formatter renders through ``self._style._fmt`` (a PercentStyle
        object created in __init__ from the fmt argument), NOT ``self._fmt``,
        so that late assignment had no effect and every line came out as the
        bare message with no "LEVELNAME:" prefix. Passing fmt here sets up the
        style correctly.
        """
        self.use_color = use_color and sys.stderr.isatty()
        super().__init__(fmt)

    def format(self, record: logging.LogRecord) -> str:
        """Format log record with optional colors.

        v0.28: previously this set record.levelname to the ANSI-wrapped
        string and never restored it. LogRecord instances are shared: the
        same record object is passed to every handler attached to the
        logger (in registration order), so once this formatter had colored
        a record, any handler processed afterwards -- e.g. the plain-text
        file handler setup_logging() adds when log_file is given -- saw the
        already-colored levelname too, leaking raw ANSI escape codes into
        the log file. The colored value is now applied to record.levelname
        only for the duration of the super().format() call and restored
        immediately after, so other handlers always see the original
        plain-text level name regardless of handler order.
        """
        if self.use_color:
            original_levelname = record.levelname
            color = self.COLORS.get(record.levelname, self.COLORS['RESET'])
            record.levelname = f"{color}{record.levelname}{self.COLORS['RESET']}"
            try:
                return super().format(record)
            finally:
                record.levelname = original_levelname
        return super().format(record)


def setup_logging(
    level: int = logging.INFO,
    use_color: bool = True,
    log_file: Optional[str] = None
) -> logging.Logger:
    """Set up structured logging for dem2dged.

    Args:
        level: logging level (DEBUG=10, INFO=20, WARNING=30, ERROR=40, CRITICAL=50)
        use_color: whether to use colored console output
        log_file: optional path to write logs to a file

    Returns:
        Configured logger instance
    """
    logger = logging.getLogger('dem2dged')
    logger.setLevel(level)

    # Remove any existing handlers
    logger.handlers = []

    # Console handler
    console_handler = logging.StreamHandler(sys.stderr)
    console_handler.setLevel(level)
    # v0.39: pass the format to the constructor so it actually takes effect
    # (see ColoredFormatter.__init__); assigning formatter._fmt afterwards was
    # a no-op because logging renders through the PercentStyle in _style.
    formatter = ColoredFormatter(use_color=use_color,
                                 fmt='%(levelname)-8s: %(message)s')
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)

    # File handler (if log_file specified)
    if log_file:
        file_handler = logging.FileHandler(log_file)
        file_handler.setLevel(level)
        file_formatter = logging.Formatter(
            '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
        )
        file_handler.setFormatter(file_formatter)
        logger.addHandler(file_handler)

    return logger


def get_logger(name: str = 'dem2dged') -> logging.Logger:
    """Get the dem2dged logger instance."""
    return logging.getLogger(name)


# Convenience functions that match dem2dged_lib's print-like interface
def log_debug(message: str) -> None:
    """Log a debug message."""
    get_logger().debug(message)


def log_info(message: str) -> None:
    """Log an info message."""
    get_logger().info(message)


def log_warning(message: str) -> None:
    """Log a warning message."""
    get_logger().warning(message)


def log_error(message: str) -> None:
    """Log an error message."""
    get_logger().error(message)


def log_critical(message: str) -> None:
    """Log a critical message."""
    get_logger().critical(message)
