"""Structured logging setup — thin wrapper around the stdlib logging module.

Two typical call sites:

    # In the background service (files + stderr):
    log = setup_logging("pry.service", log_dir=log_dir(), console=True)

    # In the TUI (stderr only, no file noise):
    log = setup_logging("pri.tui", console=True)
"""

from __future__ import annotations

import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

from .constants import DEFAULT_LOG_BACKUPS, DEFAULT_LOG_MAX_BYTES

FMT = "%(asctime)s %(name)s %(levelname)s  %(message)s"
DATE_FMT = "%Y-%m-%d %H:%M:%S"


def setup_logging(
    name: str,
    log_dir: str | Path | None = None,
    console: bool = False,
    level: str = "INFO",
    max_bytes: int = DEFAULT_LOG_MAX_BYTES,
    backups: int = DEFAULT_LOG_BACKUPS,
) -> logging.Logger:
    """Create and configure a logger.

    Args:
        name: Logger name (typically "pry.something" or "pri.something").
        log_dir: If set, writes a rotating log file to this directory.
        console: If True, also emit log lines to stderr.
        level: Minimum log level as a string ("DEBUG", "INFO", etc.).
        max_bytes: Max size per log file before rotation.
        backups: Number of rotated log files to keep.

    Returns:
        A configured logger ready for use.
    """
    logger = logging.getLogger(name)
    logger.setLevel(getattr(logging, level.upper(), logging.INFO))

    # Avoid adding duplicate handlers on repeated calls.
    if logger.handlers:
        return logger

    formatter = logging.Formatter(fmt=FMT, datefmt=DATE_FMT)

    if log_dir:
        log_dir = Path(log_dir)
        log_dir.mkdir(parents=True, exist_ok=True)
        handler = RotatingFileHandler(
            log_dir / "pry.log",
            maxBytes=max_bytes,
            backupCount=backups,
            encoding="utf-8",
        )
        handler.setFormatter(formatter)
        logger.addHandler(handler)

    if console:
        stream_handler = logging.StreamHandler(sys.stderr)
        stream_handler.setFormatter(formatter)
        logger.addHandler(stream_handler)

    return logger
