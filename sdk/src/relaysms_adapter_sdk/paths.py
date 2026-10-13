# SPDX-License-Identifier: GPL-3.0-only
"""The directories the Publisher keeps for an adapter, outside its code.

Updates replace the code, so secrets go in the config directory and anything
the adapter writes goes in the state directory.
"""

import json
import os
from pathlib import Path
from typing import Any

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
    filename: str = "credentials.json", directory: Path | None = None
) -> dict[str, Any]:
    """Read a JSON object from the config directory, with every key in lowercase.

    So `SMTP_HOST` and `smtp_host` both read as `smtp_host`, in nested objects too.
    Pass directory to read another adapter's file: the Publisher does, because
    RELAYSMS_ADAPTER_CONFIG_DIR is only set inside an adapter process.

    Raises:
        FileNotFoundError: The file doesn't exist.
        ValueError: The file isn't a JSON object, or sets a key twice in any case.
    """
    path = (directory or config_dir()) / filename
    try:
        data = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=_lower)
    except ValueError as e:
        raise ValueError(f"{path} is invalid: {e}") from e
    if not isinstance(data, dict):
        raise ValueError(f"{path} must hold a JSON object.")
    return data


def _lower(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    lowered = {}
    for key, value in pairs:
        key = key.lower()
        if key in lowered:
            raise ValueError(f"{key!r} is set twice; keys ignore case.")
        lowered[key] = value
    return lowered


def _dir(env: str) -> Path:
    value = os.environ.get(env)
    if not value:
        raise RuntimeError(f"{env} is not set.")
    return Path(value)
