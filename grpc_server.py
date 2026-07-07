# SPDX-License-Identifier: GPL-3.0-only
"""Publisher gRPC server."""

import os
import signal
import sys
from concurrent import futures
from pathlib import Path

import grpc
from grpc_interceptor import ServerInterceptor

from db import dispose_engine, get_session
from grpc_services.v3.service import PublisherServiceV3
from keys import KeyManager
from logutils import get_logger
from platforms.adapter_manager import AdapterManager
from protos.v3 import publisher_pb2_grpc as v3_grpc
from sentry_config import SENTRY_ENABLED, initialize_sentry
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


def _load_ssl_credentials(cert_path: Path, key_path: Path) -> grpc.ServerCredentials:
    """Read a certificate/key pair from disk and build gRPC server credentials."""
    for label, path in (("certificate", cert_path), ("key", key_path)):
        if not path.is_file():
            raise FileNotFoundError(f"TLS {label} not found: {path}")

    cert = cert_path.read_bytes()
    key = key_path.read_bytes()
    return grpc.ssl_server_credentials(((key, cert),))


def _build_server(max_workers: int) -> grpc.Server:
    """Construct the gRPC server and register services."""
    grpc_server = grpc.server(
        futures.ThreadPoolExecutor(max_workers=max_workers),
        interceptors=[LoggingInterceptor()],
    )

    with get_session() as db:
        key_manager = KeyManager(session=db)
        key_manager.initialize_server_identity_keys()

    PublisherServiceV3.adapter_manager = AdapterManager()
    v3_grpc.add_PublisherServicer_to_server(PublisherServiceV3(), grpc_server)

    return grpc_server


def _bind_port(
    grpc_server: grpc.Server, mode: str, hostname: str, port: str, secure_port: str
) -> None:
    """Bind the server to an insecure or TLS port depending on mode."""
    if mode != "production":
        grpc_server.add_insecure_port(f"{hostname}:{port}")
        logger.warning("Insecure mode: %s:%s", hostname, port)
        return

    cert_path = Path(get_configs("SSL_CERTIFICATE"))
    key_path = Path(get_configs("SSL_KEY"))

    try:
        credentials = _load_ssl_credentials(cert_path, key_path)
    except FileNotFoundError as e:
        logger.critical("TLS certificate or key file not found: %s", e)
        raise
    except Exception as e:
        logger.critical("Error loading TLS credentials: %s", e)
        raise

    grpc_server.add_secure_port(f"{hostname}:{secure_port}", credentials)
    logger.info("TLS enabled: %s:%s", hostname, secure_port)


def _shutdown(grpc_server: grpc.Server, signum: int) -> None:
    """Gracefully stop the server and clean up resources."""
    logger.info("Shutting down (signal %s) ...", signum)
    grpc_server.stop(grace=5).wait()
    dispose_engine()
    logger.info("Server stopped")
    sys.exit(0)


def serve() -> None:
    """Start the gRPC server and listen for requests."""
    mode = get_configs("MODE", default_value="development")
    hostname = get_configs("GRPC_HOST")
    port = get_configs("GRPC_PORT")
    secure_port = get_configs("GRPC_SSL_PORT")
    max_workers = get_configs("GRPC_MAX_WORKERS", default_value=10)

    logger.info(
        "Starting server in %s mode | host=%s | port=%s | workers=%s",
        mode,
        hostname,
        port,
        max_workers,
    )
    logger.info("Logical CPU cores available: %s", os.cpu_count())

    grpc_server = _build_server(max_workers)
    _bind_port(grpc_server, mode, hostname, port, secure_port)

    signal.signal(signal.SIGTERM, lambda signum, _frame: _shutdown(grpc_server, signum))
    signal.signal(signal.SIGINT, lambda signum, _frame: _shutdown(grpc_server, signum))

    grpc_server.start()
    grpc_server.wait_for_termination()


if __name__ == "__main__":
    serve()
