# SPDX-License-Identifier: GPL-3.0-only
"""Publisher gRPC server."""

import logging
import os
import signal
import threading
from concurrent import futures
from pathlib import Path

import grpc
from grpc_health.v1 import health, health_pb2, health_pb2_grpc

from protos.v3 import publisher_pb2_grpc as v3_grpc
from publisher import keys
from publisher.api.grpc.interceptors import (
    ErrorInterceptor,
    LoggingInterceptor,
    V1AuthInterceptor,
)
from publisher.api.grpc.v3.servicer import PublisherServicerV3
from publisher.config import GrpcConfig
from publisher.db import dispose_engine, get_session

logger = logging.getLogger(__name__)
grpc_config = GrpcConfig.get()

V3_SERVICE = "publisher.v3.Publisher"


def interceptors() -> list[grpc.ServerInterceptor]:
    """Outermost first: logging wraps error mapping, which wraps auth."""
    return [
        LoggingInterceptor(),
        ErrorInterceptor(),
        V1AuthInterceptor(
            services=[V3_SERVICE],
            nonce_ttl_seconds=grpc_config.nonce_ttl_seconds,
        ),
    ]


def _load_ssl_credentials(cert_path: Path, key_path: Path) -> grpc.ServerCredentials:
    for label, path in (("certificate", cert_path), ("key", key_path)):
        if not path.is_file():
            raise FileNotFoundError(f"TLS {label} not found: {path}")

    cert = cert_path.read_bytes()
    key = key_path.read_bytes()
    return grpc.ssl_server_credentials([(key, cert)])


def _build_server(max_workers: int) -> grpc.Server:
    grpc_server = grpc.server(
        futures.ThreadPoolExecutor(max_workers=max_workers),
        interceptors=interceptors(),
    )

    with get_session() as db:
        keys.initialize_server_identity_keys(db)

    v3_grpc.add_PublisherServicer_to_server(PublisherServicerV3(), grpc_server)

    health_servicer = health.HealthServicer()
    health_pb2_grpc.add_HealthServicer_to_server(health_servicer, grpc_server)
    health_servicer.set("", health_pb2.HealthCheckResponse.SERVING)
    health_servicer.set(V3_SERVICE, health_pb2.HealthCheckResponse.SERVING)

    return grpc_server


def _bind_port(grpc_server: grpc.Server) -> None:
    """Bind GRPC_PORT, with TLS when GRPC_TLS_ENABLED is set."""
    address = f"{grpc_config.host}:{grpc_config.port}"
    if not grpc_config.tls_enabled:
        grpc_server.add_insecure_port(address)
        logger.info("Serving without TLS: %s", address)
        return

    cert_file, key_file = grpc_config.tls_cert_file, grpc_config.tls_key_file
    assert cert_file and key_file  # config requires both when TLS is on
    try:
        credentials = _load_ssl_credentials(Path(cert_file), Path(key_file))
    except FileNotFoundError as e:
        logger.critical("TLS certificate or key file not found: %s", e)
        raise
    except Exception as e:
        logger.critical("Error loading TLS credentials: %s", e)
        raise

    grpc_server.add_secure_port(address, credentials)
    logger.info("Serving with TLS: %s", address)


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

    # Stopping inside the handler hangs if a second signal arrives mid-stop.
    stop_requested = threading.Event()

    def request_stop(signum: int, _frame) -> None:
        if not stop_requested.is_set():
            logger.info("Shutting down (signal %s) ...", signum)
        stop_requested.set()

    signal.signal(signal.SIGTERM, request_stop)
    signal.signal(signal.SIGINT, request_stop)

    grpc_server.start()
    stop_requested.wait()
    grpc_server.stop(grace=5).wait()
    dispose_engine()
    logger.info("Server stopped")
