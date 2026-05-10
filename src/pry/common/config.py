"""Configuration system — loads settings from defaults, a JSON file, and env vars.

The merge order is: built-in defaults → JSON config file → environment variables.
Environment variables take the form PRY_PORT, PRY_LOG_LEVEL, etc.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field, fields
from pathlib import Path
from typing import Any

from .constants import (
    DEFAULT_IGNORED_PATTERNS,
    DEFAULT_LOG_BACKUPS,
    DEFAULT_LOG_MAX_BYTES,
    DEFAULT_POLL_INTERVAL,
    DEFAULT_PORT,
    DEFAULT_RESULT_LIMIT,
    app_data_dir,
    local_data_dir,
    log_dir,
)


@dataclass
class PryConfig:
    """Every tunable setting for pry, with sensible defaults."""

    port: int = DEFAULT_PORT
    data_dir: Path = field(default_factory=local_data_dir)
    config_dir: Path = field(default_factory=app_data_dir)
    log_dir: Path = field(default_factory=log_dir)
    log_level: str = "INFO"
    log_max_bytes: int = DEFAULT_LOG_MAX_BYTES
    log_backups: int = DEFAULT_LOG_BACKUPS
    result_limit: int = DEFAULT_RESULT_LIMIT
    poll_interval: int = DEFAULT_POLL_INTERVAL
    ignored_patterns: list[str] = field(default_factory=lambda: list(DEFAULT_IGNORED_PATTERNS))

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for f in fields(self):
            value = getattr(self, f.name)
            if isinstance(value, Path):
                result[f.name] = str(value)
            else:
                result[f.name] = value
        return result

    def save(self, path: Path | None = None) -> None:
        """Write this config to a JSON file."""
        target = path or self.config_dir / "config.json"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(self.to_dict(), indent=2, default=str))


def _env_override(key: str, current: Any, field_type: type) -> Any:
    """Check for a PRY_* env var and coerce it to the right type."""
    env_key = f"PRY_{key.upper()}"
    raw = os.environ.get(env_key)
    if raw is None:
        return current
    if field_type is bool:
        return raw.lower() in ("1", "true", "yes")
    if field_type is int:
        try:
            return int(raw)
        except ValueError:
            return current
    if field_type is list:
        return [p.strip() for p in raw.split(",") if p.strip()]
    if field_type is Path:
        return Path(raw)
    return raw


def load_config(path: str | Path | None = None) -> PryConfig:
    """Build a PryConfig by merging defaults, a JSON file, and env vars.

    Args:
        path: Optional path to a JSON config file. If not given, looks for
              config.json in the standard config directory.

    Returns:
        A ready-to-use PryConfig.
    """
    config = PryConfig()

    # Layer 1: JSON file (overrides defaults)
    if path is None:
        path = config.config_dir / "config.json"
    else:
        path = Path(path)

    if path.exists():
        try:
            raw = json.loads(path.read_text())
            known_fields = {f.name for f in fields(PryConfig)}
            for key, value in raw.items():
                if key in known_fields:
                    field_type = type(getattr(config, key))
                    if field_type is Path and not isinstance(value, Path):
                        value = Path(value)
                    setattr(config, key, value)
        except (json.JSONDecodeError, OSError):
            pass  # Corrupt config → stick with defaults

    # Layer 2: environment variables (take highest priority)
    for f in fields(PryConfig):
        setattr(config, f.name, _env_override(f.name, getattr(config, f.name), f.type))

    return config
