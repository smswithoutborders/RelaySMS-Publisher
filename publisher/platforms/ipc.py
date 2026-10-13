# SPDX-License-Identifier: GPL-3.0-only
"""Calls into adapter processes, which run in their own venvs."""

import logging
import os
import subprocess
from pathlib import Path
from typing import Any

from publisher.config import LoggingConfig
from publisher.models.platform_adapter import PlatformAdapter
from relaysms_adapter_sdk import log, wire
from relaysms_adapter_sdk.errors import INTERNAL_ERROR, AdapterError, UpstreamError
from relaysms_adapter_sdk.manifest import ManifestError
from relaysms_adapter_sdk.manifest import load as load_manifest
from relaysms_adapter_sdk.paths import CONFIG_DIR_ENV, STATE_DIR_ENV

logger = logging.getLogger(__name__)

TIMEOUT = 60
# Adapters run third-party code, so they get only these from the environment.
PASSED_ENV = (
    "PATH",
    "HOME",
    "LANG",
    "TERM",
    "TZ",
    "HTTP_PROXY",
    "HTTPS_PROXY",
    "NO_PROXY",
)


def adapter_env(adapter: PlatformAdapter) -> dict[str, str]:
    """The environment an adapter process runs with."""
    env = {name: os.environ[name] for name in PASSED_ENV if name in os.environ}
    return env | {
        CONFIG_DIR_ENV: adapter.config_path,
        STATE_DIR_ENV: adapter.state_path,
        "LOG_LEVEL": LoggingConfig.get().log_level,
    }


def call(adapter: PlatformAdapter, method: str, request: Any) -> Any:
    """Run one adapter method in a new process and return its result.

    Raises:
        AdapterError: The adapter's error, or INTERNAL_ERROR when it can't run.
    """
    try:
        entry = load_manifest(Path(adapter.path)).entry
    except ManifestError as e:
        raise AdapterError(str(e), code=INTERNAL_ERROR) from e

    command = [f"{adapter.venv_path}/bin/python", "-m", "relaysms_adapter_sdk", entry]
    try:
        process = subprocess.run(
            command,
            input=wire.encode_request(method, request) + "\n",
            capture_output=True,
            text=True,
            env=adapter_env(adapter),
            cwd=adapter.path,
            timeout=TIMEOUT,
        )
    except subprocess.TimeoutExpired as e:
        raise UpstreamError(f"{adapter.name} took over {TIMEOUT}s to answer") from e
    except OSError as e:
        message = f"{adapter.name} can't start: {e}"
        raise AdapterError(message, code=INTERNAL_ERROR) from e

    for line in process.stderr.splitlines():
        _relay(adapter.name, line)
    if process.returncode != 0 or not process.stdout.strip():
        raise AdapterError(
            f"{adapter.name} exited with code {process.returncode}",
            code=INTERNAL_ERROR,
        )
    return wire.parse_response(process.stdout)


def _relay(adapter_name: str, line: str) -> None:
    """Log an adapter's stderr line at the level it was logged at."""
    entry = log.parse(line)
    if entry is None:
        logger.debug("[%s] %s", adapter_name, line)
        return
    level = logging.getLevelNamesMapping().get(entry["level"], logging.INFO)
    logger.log(level, "[%s] %s: %s", adapter_name, entry["logger"], entry["message"])
    if entry.get("traceback"):
        logger.log(level, "[%s] %s", adapter_name, entry["traceback"])
