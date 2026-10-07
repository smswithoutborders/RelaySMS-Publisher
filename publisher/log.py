# SPDX-License-Identifier: GPL-3.0-only
"""Logging setup, called once by each entry point."""

import logging
import os
import sys

from publisher.config import LoggingConfig


def setup_logging() -> None:
    """Configure the root logger at LOG_LEVEL."""
    # journald adds its own timestamp to each line.
    under_journald = bool(os.getenv("JOURNAL_STREAM")) and not sys.stderr.isatty()
    log_format = "%(name)s - %(levelname)s - %(message)s"
    if not under_journald:
        log_format = "%(asctime)s - " + log_format
    logging.basicConfig(level=LoggingConfig.get().log_level, format=log_format)
