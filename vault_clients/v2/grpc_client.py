"""Vault gRPC Client V2"""

import functools

import grpc

from logutils import get_logger
from protos.v2 import vault_pb2, vault_pb2_grpc
from utils import get_configs, mask_sensitive_info

logger = get_logger(__name__)


def get_channel(internal=True):
    """Get the appropriate gRPC channel based on the mode.

    Args:
        internal (bool, optional): Flag indicating whether to use internal ports.
            Defaults to True.

    Returns:
        grpc.Channel: The gRPC channel.
    """
    mode = get_configs("MODE", default_value="development")
    hostname = get_configs("VAULT_GRPC_HOST")
    if internal:
        port = get_configs("VAULT_GRPC_INTERNAL_PORT")
        secure_port = get_configs("VAULT_GRPC_INTERNAL_SSL_PORT")
    else:
        port = get_configs("VAULT_GRPC_PORT")
        secure_port = get_configs("VAULT_GRPC_SSL_PORT")

    if mode == "production":
        logger.info("Connecting to vault gRPC server at %s:%s", hostname, secure_port)
        credentials = grpc.ssl_channel_credentials()
        logger.info("Using secure channel for gRPC communication")
        return grpc.secure_channel(f"{hostname}:{secure_port}", credentials)

    logger.info("Connecting to vault gRPC server at %s:%s", hostname, port)
    logger.warning("Using insecure channel for gRPC communication")
    return grpc.insecure_channel(f"{hostname}:{port}")


def grpc_call(internal=True):
    """Decorator to handle gRPC calls."""

    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            try:
                channel = get_channel(internal)

                with channel as conn:
                    kwargs["stub"] = (
                        vault_pb2_grpc.EntityInternalStub(conn)
                        if internal
                        else vault_pb2_grpc.EntityStub(conn)
                    )
                    return func(*args, **kwargs)
            except grpc.RpcError as e:
                return None, e
            except Exception as e:
                raise e

        return wrapper

    return decorator


@grpc_call()
def decrypt_payload(payload_ciphertext, **kwargs):
    """
    Decrypts the payload.

    Args:
        payload_ciphertext (bytes): The ciphertext of the payload to be decrypted.

    Returns:
        tuple: A tuple containing:
            - server response (object): The vault server response.
            - error (Exception): The error encountered if the request fails, otherwise None.
    """
    stub = kwargs["stub"]
    device_id = kwargs.get("device_id")
    phone_number = kwargs.get("phone_number")

    request = vault_pb2.DecryptPayloadRequest(
        device_id=device_id,
        payload_ciphertext=payload_ciphertext,
        phone_number=phone_number,
    )

    identifier = mask_sensitive_info(device_id or phone_number)

    logger.debug(
        "Initiating decryption request using %s='%s'.",
        "device_id" if device_id else "phone_number",
        identifier,
    )

    response = stub.DecryptPayload(request)

    logger.info(
        "Decryption successful using %s.",
        "device_id" if device_id else "phone_number",
    )
    return response, None
