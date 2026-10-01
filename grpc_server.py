# SPDX-License-Identifier: GPL-3.0-only
"""Publisher gRPC server."""

import os
import signal
import sys
from concurrent import futures
from pathlib import Path

import grpc
from grpc_health.v1 import health, health_pb2, health_pb2_grpc
from grpc_interceptor import ServerInterceptor

from config import GrpcConfig
from db import dispose_engine, get_session
from grpc_services.v3.service import PublisherServiceV3
from keys import KeyManager
from logutils import get_logger
from platforms.adapter_manager import AdapterManager
from protos.v3 import publisher_pb2_grpc as v3_grpc

logger = get_logger("publisher.grpc.server")
grpc_config = GrpcConfig.get()


class LoggingInterceptor(ServerInterceptor):
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
    for label, path in (("certificate", cert_path), ("key", key_path)):
        if not path.is_file():
            raise FileNotFoundError(f"TLS {label} not found: {path}")

    cert = cert_path.read_bytes()
    key = key_path.read_bytes()
    return grpc.ssl_server_credentials(((key, cert),))


def _build_server(max_workers: int) -> grpc.Server:
    grpc_server = grpc.server(
        futures.ThreadPoolExecutor(max_workers=max_workers),
        interceptors=[LoggingInterceptor()],
    )

    with get_session() as db:
        key_manager = KeyManager(session=db)
        key_manager.initialize_server_identity_keys()

    PublisherServiceV3.adapter_manager = AdapterManager()
    v3_grpc.add_PublisherServicer_to_server(PublisherServiceV3(), grpc_server)

    health_servicer = health.HealthServicer()
    health_pb2_grpc.add_HealthServicer_to_server(health_servicer, grpc_server)
    health_servicer.set("", health_pb2.HealthCheckResponse.SERVING)
    health_servicer.set(
        "publisher.v3.Publisher", health_pb2.HealthCheckResponse.SERVING
    )

    return grpc_server


def _bind_port(grpc_server: grpc.Server) -> None:
    """Bind GRPC_PORT, with TLS when GRPC_TLS_ENABLED is set."""
    address = f"{grpc_config.host}:{grpc_config.port}"
    if not grpc_config.tls_enabled:
        grpc_server.add_insecure_port(address)
        logger.info("Serving without TLS: %s", address)
        return

    try:
        credentials = _load_ssl_credentials(
            Path(grpc_config.tls_cert_file), Path(grpc_config.tls_key_file)
        )
    except FileNotFoundError as e:
        logger.critical("TLS certificate or key file not found: %s", e)
        raise
    except Exception as e:
        logger.critical("Error loading TLS credentials: %s", e)
        raise

    grpc_server.add_secure_port(address, credentials)
    logger.info("Serving with TLS: %s", address)


def _shutdown(grpc_server: grpc.Server, signum: int) -> None:
    logger.info("Shutting down (signal %s) ...", signum)
    grpc_server.stop(grace=5).wait()
    dispose_engine()
    logger.info("Server stopped")
    sys.exit(0)


def serve() -> None:
    logger.info(
        "Starting server | tls=%s | host=%s | port=%s | workers=%s",
        grpc_config.tls_enabled,
        grpc_config.host,
        grpc_config.port,
        grpc_config.max_workers,
    )
    logger.info("Logical CPU cores available: %s", os.cpu_count())

    grpc_server = _build_server(grpc_config.max_workers)
    _bind_port(grpc_server)

    signal.signal(signal.SIGTERM, lambda signum, _frame: _shutdown(grpc_server, signum))
    signal.signal(signal.SIGINT, lambda signum, _frame: _shutdown(grpc_server, signum))

    grpc_server.start()
    grpc_server.wait_for_termination()


if __name__ == "__main__":
    serve()
