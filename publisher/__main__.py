# SPDX-License-Identifier: GPL-3.0-only
"""Run the CLI: python -m publisher GROUP COMMAND."""

from publisher.cli import cli
from publisher.log import setup_logging

setup_logging()
cli()
