# SPDX-License-Identifier: GPL-3.0-only
"""Run the SMTP listener: python -m publisher.smtp."""

from publisher.log import setup_logging
from publisher.smtp.listener import main

setup_logging()
main()
