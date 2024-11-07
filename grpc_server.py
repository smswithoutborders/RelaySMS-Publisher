"""Publisher gRPC server"""

import logging
import os
from concurrent import futures

import grpc
from grpc_interceptor import ServerInterceptor
import publisher_pb2_grpc

from utils import get_configs
from sentry_config import initialize_sentry, SENTRY_ENABLED
from grpc_publisher_service import PublisherService

logging.basicConfig(
    level=logging.INFO, format=("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
)
logger = logging.getLogger("publisher.grpc.server")

if SENTRY_ENABLED:
    initialize_sentry()


class LoggingInterceptor(ServerInterceptor):
    """
    gRPC server interceptor for logging requests.
    """

    def __init__(self):
        """
        Initialize the LoggingInterceptor.
        """
        self.logger = logger
        self.server_protocol = "HTTP/2.0"

    def intercept(self, method, request_or_iterator, context, method_name):
        """
        Intercept method calls for each incoming RPC.
        """
        response = method(request_or_iterator, context)
        if context.details():
            self.logger.error(
                "%s %s - %s -",
                method_name,
                self.server_protocol,
                str(context.code()).split(".")[1],
            )
        else:
            self.logger.info("%s %s - %s -", method_name, self.server_protocol, "OK")
        return response


def serve():
    """
    Starts the gRPC server and listens for requests using a thread pool.
    """
    mode = get_configs("MODE", False, "development")
    server_certificate = get_configs("SSL_CERTIFICATE")
    private_key = get_configs("SSL_KEY")
    hostname = get_configs("GRPC_HOST")
    secure_port = get_configs("GRPC_SSL_PORT")
    port = get_configs("GRPC_PORT")

    num_cpu_cores = os.cpu_count()
    max_workers = 10

    logger.info("Starting server in %s mode...", mode)
    logger.info("Hostname: %s", hostname)
    logger.info("Insecure port: %s", port)
    logger.info("Secure port: %s", secure_port)
    logger.info("Logical CPU cores available: %s", num_cpu_cores)
    logger.info("gRPC server max workers: %s", max_workers)

    grpc_server = grpc.server(
        futures.ThreadPoolExecutor(max_workers=max_workers),
        interceptors=[LoggingInterceptor()],
    )
    publisher_pb2_grpc.add_PublisherServicer_to_server(PublisherService(), grpc_server)

    if mode == "production":
        try:
            with open(server_certificate, "rb") as f:
                server_certificate_data = f.read()
            with open(private_key, "rb") as f:
                private_key_data = f.read()

            server_credentials = grpc.ssl_server_credentials(
                ((private_key_data, server_certificate_data),)
            )
            grpc_server.add_secure_port(f"{hostname}:{secure_port}", server_credentials)
            logger.info(
                "TLS is enabled: The server is securely running at %s:%s",
                hostname,
                secure_port,
            )
        except FileNotFoundError as e:
            logger.critical(
                (
                    "Unable to start server: TLS certificate or key file not found: %s. "
                    "Please check your configuration."
                ),
                e,
            )
            raise
        except Exception as e:
            logger.critical(
                (
                    "Unable to start server: Error loading TLS credentials: %s. "
                    "Please check your configuration."
                ),
                e,
            )
            raise
    else:
        grpc_server.add_insecure_port(f"{hostname}:{port}")
        logger.warning(
            "The server is running in insecure mode at %s:%s", hostname, port
        )

    grpc_server.start()

    try:
        grpc_server.wait_for_termination()
    except KeyboardInterrupt:
        logger.info("Shutting down the server...")
        grpc_server.stop(0)
        logger.info("The server has stopped successfully")


if __name__ == "__main__":
    serve()
