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


def configure(stream: TextIO = sys.stderr, package: str | None = None) -> None:
    """Send log records to stream as JSON lines.

    The adapter's package and the SDK log at LOG_LEVEL, INFO by default. Other
    libraries the adapter uses send only warnings and errors, unless LOG_LEVEL
    is DEBUG.
    """
    name = os.environ.get("LOG_LEVEL", "INFO").upper()
    known = logging.getLevelNamesMapping().get(name)
    level = known or logging.INFO

    handler = logging.StreamHandler(stream)
    handler.setFormatter(JSONFormatter())
    libraries = level if level <= logging.DEBUG else max(level, logging.WARNING)
    logging.basicConfig(level=libraries, handlers=[handler], force=True)
    for own in (__package__, package):
        if own:
            logging.getLogger(own).setLevel(level)
    if known is None:
        logging.getLogger(__name__).warning("Unknown LOG_LEVEL %r, using INFO.", name)
