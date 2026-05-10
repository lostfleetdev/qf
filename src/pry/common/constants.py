"""Shared constants — ports, paths, and defaults used across pry."""

import os
import sys
from pathlib import Path

APP_NAME = "pry"
DEFAULT_PORT = 7890
DEFAULT_RESULT_LIMIT = 50
DEFAULT_POLL_INTERVAL = 5  # seconds between USN journal checks
DEFAULT_LOG_MAX_BYTES = 10 * 1024 * 1024  # 10 MB
DEFAULT_LOG_BACKUPS = 5

# Patterns skipped during directory scans.
DEFAULT_IGNORED_PATTERNS = [
    "$RECYCLE.BIN",
    "System Volume Information",
    "Windows",
    "Program Files",
    "Program Files (x86)",
    "ProgramData",
    ".git",
    "__pycache__",
    "node_modules",
    ".venv",
    "AppData",
]


def app_data_dir() -> Path:
    """Config directory: %APPDATA%/pry on Windows, ~/.pry elsewhere."""
    if sys.platform == "win32":
        base = os.environ.get("APPDATA", os.path.expanduser("~"))
    else:
        base = os.environ.get("XDG_CONFIG_HOME", os.path.expanduser("~/.config"))
    return Path(base) / APP_NAME


def local_data_dir() -> Path:
    """Data directory: %LOCALAPPDATA%/pry on Windows, ~/.local/share/pry elsewhere."""
    if sys.platform == "win32":
        base = os.environ.get("LOCALAPPDATA", os.path.expanduser("~"))
    else:
        base = os.environ.get("XDG_DATA_HOME", os.path.expanduser("~/.local/share"))
    return Path(base) / APP_NAME


def log_dir() -> Path:
    """Directory where log files live."""
    return local_data_dir() / "logs"


def db_path() -> Path:
    """Path to the SQLite index database."""
    return local_data_dir() / "pry.db"
