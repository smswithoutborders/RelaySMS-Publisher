# SPDX-License-Identifier: GPL-3.0-only
"""ExchangeOAuth2CodeAndStore gRPC service handler."""

import grpc
from cryptography.hazmat.primitives.asymmetric.x25519 import (
    X25519PrivateKey,
    X25519PublicKey,
)
from sqlalchemy import insert

from db import get_session
from grpc_services.v3.utils import get_oauth2_adapter
from logutils import get_logger
from models.client_ephemeral_key import ClientEphemeralKey
from models.server_ephemeral_key import ServerEphemeralKey
from models.token import create as create_token
from models.token_hash import create as create_token_hash
from platforms.adapter_ipc_handler import AdapterIPCHandler
from protos.v3 import publisher_pb2

logger = get_logger(__name__)


def _validate_client_ephemeral_public_keys(keys) -> None:
    """Validate client ephemeral public keys format and count."""
    if len(keys) != 256:
        raise ValueError(
            f"client_ephemeral_public_keys must contain exactly 256 keys, "
            f"got {len(keys)}"
        )
    for key_obj in keys:
        if len(key_obj.public_key) != 32:
            raise ValueError(
                f"Invalid key for key_id {key_obj.key_id}: "
                f"must be 32 bytes, got {len(key_obj.public_key)}"
            )
        try:
            X25519PublicKey.from_public_bytes(key_obj.public_key)
        except Exception as e:
            raise ValueError(
                f"Invalid cryptographic key for key_id {key_obj.key_id}: {e}"
            )


def ExchangeOAuth2CodeAndStore(self, request, context):
    """Exchange an OAuth2 authorization code for a token."""

    response = publisher_pb2.ExchangeOAuth2CodeAndStoreResponse

    _, auth_error = self.handle_v1_request_auth(context, response)
    if auth_error:
        return auth_error

    invalid = self.handle_request_field_validation(
        context, request, response, ["platform", "authorization_code"]
    )
    if invalid:
        return invalid

    try:
        _validate_client_ephemeral_public_keys(request.client_ephemeral_public_keys)
    except ValueError as exc:
        return self.handle_create_grpc_error_response(
            context,
            response,
            exc,
            grpc.StatusCode.INVALID_ARGUMENT,
        )

    try:
        adapter = get_oauth2_adapter(request.platform)

        pipe = AdapterIPCHandler.invoke(
            adapter_path=adapter["path"],
            venv_path=adapter["venv_path"],
            method="exchange_code_and_fetch_user_info",
            params={
                "code": request.authorization_code,
                "code_verifier": request.code_verifier or None,
                "redirect_url": request.redirect_url or None,
                "request_identifier": request.request_identifier or None,
                "base_path": adapter["assets_path"],
            },
        )

        if pipe.get("error"):
            return self.handle_create_grpc_error_response(
                context,
                response,
                pipe["error"],
                grpc.StatusCode.INVALID_ARGUMENT,
                error_type="UNKNOWN",
            )

        result = pipe["result"]

        with get_session() as s:
            token = create_token(
                platform=request.platform.lower(),
                token_data={
                    "account_id": result["userinfo"]["account_identifier"],
                    "token": result["token"],
                },
                session=s,
            )

            token_hash_obj, raw_token = create_token_hash(token_id=token.id, session=s)

            server_keypairs = [X25519PrivateKey.generate() for _ in range(256)]
            s.execute(
                insert(ServerEphemeralKey),
                [
                    {
                        "token_hash_id": token_hash_obj.id,
                        "key_index": i,
                        "private_key": kp.private_bytes_raw(),
                        "public_key": kp.public_key().public_bytes_raw(),
                        "used": False,
                    }
                    for i, kp in enumerate(server_keypairs)
                ],
            )

            s.execute(
                insert(ClientEphemeralKey),
                [
                    {
                        "token_hash_id": token_hash_obj.id,
                        "key_index": k.key_id,
                        "public_key": k.public_key,
                        "used": False,
                    }
                    for k in request.client_ephemeral_public_keys
                ],
            )

            s.flush()
            s.refresh(token_hash_obj)

            server_keys = [
                publisher_pb2.PublicKey(
                    key_id=k.key_index,
                    public_key=k.public_key,
                )
                for k in token_hash_obj.server_keys.all()
            ]

        return response(
            success=True,
            message="Successfully fetched and stored token",
            account_identifier=result["userinfo"]["account_identifier"],
            token_ciphertext=raw_token,
            token_id=token.token_id,
            server_ephemeral_public_keys=server_keys,
        )

    except NotImplementedError as exc:
        return self.handle_create_grpc_error_response(
            context,
            response,
            exc,
            grpc.StatusCode.UNIMPLEMENTED,
        )

    except ValueError as exc:
        logger.error("%s", exc)
        return self.handle_create_grpc_error_response(
            context,
            response,
            exc,
            grpc.StatusCode.INTERNAL,
            user_msg="Oops! Something went wrong. Please try again later.",
        )

    except Exception as exc:
        return self.handle_create_grpc_error_response(
            context,
            response,
            exc,
            grpc.StatusCode.INTERNAL,
            user_msg="Oops! Something went wrong. Please try again later.",
            error_type="UNKNOWN",
        )
