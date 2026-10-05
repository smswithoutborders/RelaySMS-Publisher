# SPDX-License-Identifier: GPL-3.0-only
"""Run the gRPC server: python -m publisher.api.grpc."""

from publisher.api.grpc.server import serve
from publisher.log import setup_logging

setup_logging()
serve()
