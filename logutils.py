# SPDX-License-Identifier: GPL-3.0-only

import logging
import os
import sys

from config import LoggingConfig

_UNDER_JOURNALD = bool(os.getenv("JOURNAL_STREAM")) and not sys.stderr.isatty()

_LOG_FORMAT = (
    "%(name)s - %(levelname)s - %(message)s"
    if _UNDER_JOURNALD
    else "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)

logging.basicConfig(level=LoggingConfig.get().log_level, format=_LOG_FORMAT)


def get_logger(name: str = None) -> logging.Logger:
    return logging.getLogger(name)
