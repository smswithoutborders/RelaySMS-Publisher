# SPDX-License-Identifier: GPL-3.0-only
"""The kombu transport for the SQLite broker, with its polls kept out of traces."""

from contextlib import nullcontext
from typing import override

from kombu.transport import sqlalchemy

try:
    from opentelemetry.instrumentation.utils import (  # pyright: ignore[reportMissingImports]
        suppress_instrumentation,
    )
except ImportError:  # requirements-observability.txt isn't installed
    suppress_instrumentation = nullcontext


class Channel(sqlalchemy.Channel):
    @override
    def _get(self, queue):
        with suppress_instrumentation():
            return super()._get(queue)


class Transport(sqlalchemy.Transport):
    Channel = Channel
