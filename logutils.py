# SPDX-License-Identifier: GPL-3.0-only

import logging
import os
import sys

LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
numeric_level = getattr(logging, LOG_LEVEL, None)

if not isinstance(numeric_level, int):
    raise ValueError(f"Invalid log level: {LOG_LEVEL}")

_UNDER_JOURNALD = bool(os.getenv("JOURNAL_STREAM")) and not sys.stderr.isatty()

_LOG_FORMAT = (
    "%(name)s - %(levelname)s - %(message)s"
    if _UNDER_JOURNALD
    else "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)

logging.basicConfig(level=numeric_level, format=_LOG_FORMAT)


def get_logger(name: str = None) -> logging.Logger:
    """
    Retrieves a logger instance configured with the specified name.

    Args:
        name (str, optional): The name of the logger. If None, the root logger is
            returned.

    Returns:
        logging.logger: A configured logger instance.
    """
    return logging.getLogger(name)
