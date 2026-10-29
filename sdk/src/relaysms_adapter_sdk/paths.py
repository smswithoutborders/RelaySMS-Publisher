# SPDX-License-Identifier: GPL-3.0-only
"""The directories the Publisher keeps for an adapter, outside its code.

Secrets go in the config directory and anything the adapter writes goes in the
state directory.
"""

import json
import os
import tempfile
from collections.abc import Iterable
from pathlib import Path
from typing import Any

CREDENTIALS_FILE = "credentials.json"


class ConfigError(ValueError):
    """Settings, or a settings file, that don't fit what the adapter declares."""


CONFIG_DIR_ENV = "RELAYSMS_ADAPTER_CONFIG_DIR"
STATE_DIR_ENV = "RELAYSMS_ADAPTER_STATE_DIR"


def config_dir() -> Path:
    """Return the directory holding the adapter's credentials and settings."""
    return _dir(CONFIG_DIR_ENV)


def state_dir() -> Path:
    """Return the directory the adapter writes to, creating it if needed."""
    path = _dir(STATE_DIR_ENV)
    path.mkdir(parents=True, exist_ok=True)
    return path


def read_config(
    filename: str = CREDENTIALS_FILE, directory: Path | None = None
) -> dict[str, Any]:
    """Read a JSON object from the config directory, with every key in lowercase.

    `SMTP_HOST` and `smtp_host` both read as `smtp_host`, in nested objects too.
    Pass directory to read a file outside an adapter process, where
    RELAYSMS_ADAPTER_CONFIG_DIR isn't set.

    Raises:
        FileNotFoundError: The file doesn't exist.
        ConfigError: The file isn't a JSON object, or sets a key twice in any case.
    """
    path = (directory or config_dir()) / filename
    try:
        data = json.loads(
            path.read_text(encoding="utf-8"), object_pairs_hook=lowercase_keys
        )
    except ValueError as e:
        raise ConfigError(f"{path} is invalid: {e}") from e
    if not isinstance(data, dict):
        raise ConfigError(f"{path} must hold a JSON object.")
    return data


def write_config(
    settings: dict[str, Any],
    filename: str = CREDENTIALS_FILE,
    directory: Path | None = None,
) -> Path:
    """Atomically replace a JSON file in the config directory, readable by its owner."""
    path = (directory or config_dir()) / filename
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(dir=path.parent, prefix=f".{filename}-")
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as file:
            json.dump(settings, file, indent=2)
        os.replace(temporary, path)
    except BaseException:
        Path(temporary).unlink(missing_ok=True)
        raise
    return path


def lowercase_keys(pairs: Iterable[tuple[str, Any]]) -> dict[str, Any]:
    """Build a dict with lowercase keys.

    Raises:
        ValueError: Two keys differ only in case.
    """
    lowered = {}
    for key, value in pairs:
        key = key.lower()
        if key in lowered:
            raise ValueError(f"{key!r} is set twice (keys ignore case).")
        lowered[key] = value
    return lowered


def _dir(env: str) -> Path:
    value = os.environ.get(env)
    if not value:
        raise RuntimeError(f"{env} is not set.")
    return Path(value)
