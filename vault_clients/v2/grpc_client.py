# SPDX-License-Identifier: GPL-3.0-only
"""Vault gRPC Client V2"""

import functools

import grpc

from logutils import get_logger
from protos.v2 import vault_pb2, vault_pb2_grpc
from utils import get_configs

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
def store_entity_token(**kwargs):
    """Store an entity token in the vault."""
    stub = kwargs["stub"]
    metadata = kwargs["metadata"]
    token = kwargs["token"]
    platform = kwargs["platform"]
    account_identifier = kwargs["account_identifier"]

    request = vault_pb2.StoreEntityTokenRequest(
        token=token,
        platform=platform,
        account_identifier=account_identifier,
    )

    logger.debug("Initiating store token for platform '%s'.", platform)

    response = stub.StoreEntityToken(request, metadata=metadata)

    logger.info("Successfully stored token for platform '%s'", platform)
    return response, None


@grpc_call(False)
def list_entity_stored_tokens(**kwargs):
    """Lists an entity's stored tokens from the vault."""
    stub = kwargs["stub"]
    metadata = kwargs["metadata"]
    request = vault_pb2.ListEntityStoredTokensRequest()

    logger.debug("Initiating request to list stored tokens.")

    response = stub.ListEntityStoredTokens(request, metadata=metadata)
    tokens = response.stored_tokens

    logger.info("Successfully retrieved stored tokens.")
    return tokens, None


@grpc_call()
def get_entity_access_token(**kwargs):
    """Retrieves an entity access token."""
    stub = kwargs["stub"]
    platform = kwargs["platform"]
    account_identifier = kwargs["account_identifier"]
    metadata = kwargs.get("metadata")
    device_id = kwargs.get("device_id")
    phone_number = kwargs.get("phone_number")

    request = vault_pb2.GetEntityAccessTokenRequest(
        device_id=device_id,
        platform=platform,
        account_identifier=account_identifier,
        phone_number=phone_number,
    )

    logger.debug("Initiating access token retrieval for platform '%s'.", platform)

    response = stub.GetEntityAccessToken(request, metadata=metadata)

    logger.info("Successfully retrieved access token for platform '%s'.", platform)
    return response, None


@grpc_call()
def delete_entity_token(**kwargs):
    """Delete an entity's token in the vault."""
    stub = kwargs["stub"]
    metadata = kwargs["metadata"]
    platform = kwargs["platform"]
    account_identifier = kwargs["account_identifier"]

    request = vault_pb2.DeleteEntityTokenRequest(
        platform=platform, account_identifier=account_identifier
    )

    logger.debug("Initiating token deletion for platform '%s'.", platform)

    response = stub.DeleteEntityToken(request, metadata=metadata)

    logger.info("Successfully deleted token for platform '%s'.", platform)
    return response, None


@grpc_call()
def update_entity_token(**kwargs):
    """Update an entity's token in the vault."""
    stub = kwargs["stub"]
    token = kwargs["token"]
    platform = kwargs["platform"]
    account_identifier = kwargs["account_identifier"]
    device_id = kwargs.get("device_id")
    phone_number = kwargs.get("phone_number")

    request = vault_pb2.UpdateEntityTokenRequest(
        device_id=device_id,
        token=token,
        platform=platform,
        account_identifier=account_identifier,
        phone_number=phone_number,
    )

    logger.debug("Initiating token update for platform '%s'.", platform)

    response = stub.UpdateEntityToken(request)

    logger.info("Successfully updated token for platform '%s'.", platform)
    return response, None


@grpc_call()
def decrypt_payload(**kwargs):
    """Decrypts the payload."""
    stub = kwargs["stub"]
    payload_ciphertext = kwargs["payload_ciphertext"]
    device_id = kwargs.get("device_id")
    phone_number = kwargs.get("phone_number")

    request = vault_pb2.DecryptPayloadRequest(
        device_id=device_id,
        payload_ciphertext=payload_ciphertext,
        phone_number=phone_number,
    )

    logger.debug("Initiating decryption request.")

    response = stub.DecryptPayload(request)

    logger.info("Decryption successful.")
    return response, None


@grpc_call()
def encrypt_payload(**kwargs):
    """Encrypts the payload."""
    stub = kwargs["stub"]
    payload_plaintext = kwargs["payload_plaintext"]
    device_id = kwargs.get("device_id")
    request = vault_pb2.EncryptPayloadRequest(
        device_id=device_id, payload_plaintext=payload_plaintext
    )

    logger.debug("Initiating encryption request.")

    response = stub.EncryptPayload(request)

    logger.info("Successfully encrypted payload.")
    return response, None
