# SPDX-License-Identifier: GPL-3.0-only
"""Logs to standard error as JSON lines the Publisher reads back at their level."""

import json
import logging
import os
import sys
from typing import TextIO


class JSONFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        entry = {
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if record.exc_info:
            entry["traceback"] = self.formatException(record.exc_info)
        return json.dumps(entry, ensure_ascii=False)


def parse(line: str) -> dict[str, str] | None:
    """Read back a line JSONFormatter wrote; None for anything else."""
    try:
        entry = json.loads(line)
    except json.JSONDecodeError:
        return None
    if isinstance(entry, dict) and {"level", "logger", "message"} <= entry.keys():
        return entry
    return None


def configure(stream: TextIO = sys.stderr) -> None:
    """Send every log record to stream at LOG_LEVEL, INFO by default."""
    name = os.environ.get("LOG_LEVEL", "INFO").upper()
    level = logging.getLevelNamesMapping().get(name)

    handler = logging.StreamHandler(stream)
    handler.setFormatter(JSONFormatter())
    logging.basicConfig(level=level or logging.INFO, handlers=[handler], force=True)
    if level is None:
        logging.getLogger(__name__).warning("Unknown LOG_LEVEL %r, using INFO.", name)
