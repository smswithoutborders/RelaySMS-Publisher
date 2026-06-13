# SPDX-License-Identifier: GPL-3.0-only
"""ExchangeOAuth2CodeAndStore gRPC service handler."""

import grpc
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PublicKey

from db import get_session
from grpc_services.v3.utils import create_token_pools_and_encrypt, get_oauth2_adapter
from logutils import get_logger
from models.token import create as create_token
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
        context,
        request,
        response,
        ["platform", "authorization_code", "client_ephemeral_public_keys"],
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

            (token_ciphertext, kid_index, server_public_keys) = (
                create_token_pools_and_encrypt(
                    token_id=token.id,
                    client_ephemeral_public_keys=request.client_ephemeral_public_keys,
                    session=s,
                )
            )

        return response(
            success=True,
            message="Successfully fetched and stored token",
            account_identifier=result["userinfo"]["account_identifier"],
            token_ciphertext=token_ciphertext,
            token_id=token.token_id,
            server_ephemeral_public_keys=server_public_keys,
            key_id=kid_index,
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
