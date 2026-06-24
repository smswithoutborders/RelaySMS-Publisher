# SPDX-License-Identifier: GPL-3.0-only
"""Publisher gRPC server"""

import os
import signal
import sys
from concurrent import futures

import grpc
from grpc_interceptor import ServerInterceptor

from db import dispose_engine
from grpc_services.v3.service import PublisherServiceV3
from logutils import get_logger
from platforms.adapter_manager import AdapterManager
from protos.v3 import publisher_pb2_grpc as v3_grpc
from sentry_config import SENTRY_ENABLED, initialize_sentry
from server_identity_keys import initialize_server_identity_keys
from utils import get_configs

logger = get_logger("publisher.grpc.server")

if SENTRY_ENABLED:
    initialize_sentry()


class LoggingInterceptor(ServerInterceptor):
    """gRPC server interceptor for logging requests."""

    server_protocol = "HTTP/2.0"

    def intercept(self, method, request_or_iterator, context, method_name):
        context.method_name = method_name
        response = method(request_or_iterator, context)
        if context.details():
            logger.error(
                "%s %s - %s -",
                method_name,
                self.server_protocol,
                str(context.code()).split(".")[1],
            )
        else:
            logger.info("%s %s - OK -", method_name, self.server_protocol)
        return response


def serve():
    """Start the gRPC server and listen for requests."""
    mode = get_configs("MODE", False, "development")
    hostname = get_configs("GRPC_HOST")
    port = get_configs("GRPC_PORT")
    secure_port = get_configs("GRPC_SSL_PORT")

    max_workers = 10
    logger.info(
        "Starting server in %s mode | host=%s | port=%s | workers=%s",
        mode,
        hostname,
        port,
        max_workers,
    )
    logger.info("Logical CPU cores available: %s", os.cpu_count())

    grpc_server = grpc.server(
        futures.ThreadPoolExecutor(max_workers=max_workers),
        interceptors=[LoggingInterceptor()],
    )

    initialize_server_identity_keys()

    PublisherServiceV3.adapter_manager = AdapterManager()
    v3_grpc.add_PublisherServicer_to_server(PublisherServiceV3(), grpc_server)

    if mode == "production":
        try:
            with open(get_configs("SSL_CERTIFICATE"), "rb") as f:
                cert = f.read()
            with open(get_configs("SSL_KEY"), "rb") as f:
                key = f.read()
            grpc_server.add_secure_port(
                f"{hostname}:{secure_port}",
                grpc.ssl_server_credentials(((key, cert),)),
            )
            logger.info("TLS enabled: %s:%s", hostname, secure_port)
        except FileNotFoundError as e:
            logger.critical("TLS certificate or key file not found: %s", e)
            raise
        except Exception as e:
            logger.critical("Error loading TLS credentials: %s", e)
            raise
    else:
        grpc_server.add_insecure_port(f"{hostname}:{port}")
        logger.warning("Insecure mode: %s:%s", hostname, port)

    grpc_server.start()

    def shutdown(signum, frame):
        logger.info("Shutting down (signal %s) ...", signum)
        grpc_server.stop(grace=5)
        dispose_engine()
        logger.info("Server stopped")
        sys.exit(0)

    signal.signal(signal.SIGTERM, shutdown)
    signal.signal(signal.SIGINT, shutdown)

    grpc_server.wait_for_termination()


if __name__ == "__main__":
    serve()
