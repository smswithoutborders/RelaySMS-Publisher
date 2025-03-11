"""Vault gRPC Client"""

import functools
import grpc

import vault_pb2
import vault_pb2_grpc

from utils import get_configs, mask_sensitive_info
from logutils import get_logger

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
def store_entity_token(long_lived_token, token, platform, account_identifier, **kwargs):
    """Store an entity token in the vault.

    Args:
        long_lived_token (str): The long-lived token.
        token (str): The token to store.
        platform (str): The platform name.
        account_identifier (str): The account identifier.

    Returns:
        tuple: A tuple containing:
            - server response (object): The vault server response.
            - error (Exception): The error encountered if the request fails, otherwise None.
    """
    stub = kwargs["stub"]

    request = vault_pb2.StoreEntityTokenRequest(
        long_lived_token=long_lived_token,
        token=token,
        platform=platform,
        account_identifier=account_identifier,
    )

    logger.debug("Storing token for platform '%s'", platform)
    response = stub.StoreEntityToken(request)
    logger.info("Successfully stored token for platform '%s'", platform)
    return response, None


@grpc_call(False)
def list_entity_stored_tokens(long_lived_token, **kwargs):
    """Fetches and lists an entity's stored tokens from the vault.

    Args:
        long_lived_token (str): The long-lived token used to authenticate
            the request.

    Returns:
        tuple: A tuple containing:
            - list: A list of stored tokens if the request is successful.
            - error (Exception): The error encountered if the request fails,
                otherwise None.
    """
    stub = kwargs["stub"]
    request = vault_pb2.ListEntityStoredTokensRequest(long_lived_token=long_lived_token)

    logger.debug(
        "Sending request to list stored tokens for long_lived_token: %s",
        long_lived_token,
    )
    response = stub.ListEntityStoredTokens(request)
    tokens = response.stored_tokens

    logger.info("Successfully retrieved stored tokens.")
    return tokens, None


@grpc_call()
def get_entity_access_token(platform, account_identifier, **kwargs):
    """
    Retrieves an entity access token.

    Args:
        device_id (str, optional): The ID of the device.
        long_lived_token (str, optional): The long-lived token used to authenticate
        platform (str): The platform name.
        account_identifier (str): The account identifier.

    Returns:
        tuple: A tuple containing:
            - server response (object): The vault server response.
            - error (Exception): The error encountered if the request fails, otherwise None.
    """
    stub = kwargs["stub"]
    device_id = kwargs.get("device_id")
    long_lived_token = kwargs.get("long_lived_token")
    phone_number = kwargs.get("phone_number")

    request = vault_pb2.GetEntityAccessTokenRequest(
        device_id=device_id,
        long_lived_token=long_lived_token,
        platform=platform,
        account_identifier=account_identifier,
        phone_number=phone_number,
    )

    identifier = mask_sensitive_info(long_lived_token or device_id or phone_number)
    id_type = (
        "long_lived_token"
        if long_lived_token
        else "device_id" if device_id else "phone_number"
    )

    logger.debug("Requesting access tokens using %s='%s'...", id_type, identifier)

    response = stub.GetEntityAccessToken(request)

    logger.info("Successfully retrieved access token using %s.", id_type)

    return response, None


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


@grpc_call()
def encrypt_payload(device_id, payload_plaintext, **kwargs):
    """
    Encrypts the payload.

    Args:
        device_id (str): The ID of the device.
        payload_plaintext (str): The plaintext of the payload to be encrypted.

    Returns:
        tuple: A tuple containing:
            - server response (object): The vault server response.
            - error (Exception): The error encountered if the request fails, otherwise None.
    """
    stub = kwargs["stub"]
    request = vault_pb2.EncryptPayloadRequest(
        device_id=device_id, payload_plaintext=payload_plaintext
    )

    logger.debug(
        "Sending request to encrypt payload for device_id: %s",
        device_id,
    )
    response = stub.EncryptPayload(request)
    logger.info("Successfully encrypted payload.")
    return response, None


@grpc_call()
def update_entity_token(token, platform, account_identifier, **kwargs):
    """Update an entity's token in the vault.

    Args:
        device_id (str): The ID of the device.
        token (str): The token to store.
        platform (str): The platform name.
        account_identifier (str): The account identifier.

    Returns:
        tuple: A tuple containing:
            - server response (object): The vault server response.
            - error (Exception): The error encountered if the request fails, otherwise None.
    """
    stub = kwargs["stub"]
    device_id = kwargs.get("device_id")
    phone_number = kwargs.get("phone_number")

    request = vault_pb2.UpdateEntityTokenRequest(
        device_id=device_id,
        token=token,
        platform=platform,
        account_identifier=account_identifier,
        phone_number=phone_number,
    )

    identifier = mask_sensitive_info(device_id or phone_number)

    logger.debug(
        "Starting token update for platform '%s' using %s='%s'.",
        platform,
        "device_id" if device_id else "phone_number",
        identifier,
    )

    response = stub.UpdateEntityToken(request)

    logger.info(
        "Token update successful for platform '%s' using %s.",
        platform,
        "device_id" if device_id else "phone_number",
    )

    return response, None


@grpc_call()
def delete_entity_token(long_lived_token, platform, account_identifier, **kwargs):
    """Delete an entity's token in the vault.

    Args:
        long_lived_token (str): The long-lived token used to authenticate
        platform (str): The platform name.
        account_identifier (str): The account identifier.

    Returns:
        tuple: A tuple containing:
            - server response (object): The vault server response.
            - error (Exception): The error encountered if the request fails, otherwise None.
    """
    stub = kwargs["stub"]
    request = vault_pb2.DeleteEntityTokenRequest(
        long_lived_token=long_lived_token,
        platform=platform,
        account_identifier=account_identifier,
    )

    logger.debug("Deleting token for platform '%s'", platform)
    response = stub.DeleteEntityToken(request)
    logger.info("Successfully deleted token for platform '%s'", platform)
    return response, None
