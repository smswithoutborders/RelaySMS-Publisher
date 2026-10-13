# SPDX-License-Identifier: GPL-3.0-only
"""The directories the Publisher keeps for an adapter, outside its code.

Updates replace the code, so secrets go in the config directory and anything
the adapter writes goes in the state directory.
"""

import os
from pathlib import Path

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


def _dir(env: str) -> Path:
    value = os.environ.get(env)
    if not value:
        raise RuntimeError(f"{env} is not set.")
    return Path(value)
