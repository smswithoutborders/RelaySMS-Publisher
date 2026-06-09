# SPDX-License-Identifier: GPL-3.0-only
"""UploadClientEphemeralPublicKeys gRPC service handler."""

import grpc
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PublicKey
from sqlalchemy import insert

from db import get_session
from models.client_ephemeral_key import ClientEphemeralKey
from models.token import Token
from models.token_hash import TokenHash
from protos.v3 import publisher_pb2


def _validate_client_ephemeral_public_keys(keys) -> None:
    """Validate client ephemeral public keys format and count."""
    if len(keys) != 256:
        raise ValueError(
            f"client_ephemeral_public_keys must contain exactly 256 keys, got {len(keys)}"
        )
    for key_obj in keys:
        if len(key_obj.public_key) != 32:
            raise ValueError(
                f"Invalid key for key_id {key_obj.key_id}: must be 32 bytes, got {len(key_obj.public_key)}"
            )
        try:
            X25519PublicKey.from_public_bytes(key_obj.public_key)
        except Exception as e:
            raise ValueError(
                f"Invalid cryptographic key for key_id {key_obj.key_id}: {e}"
            )


def UploadClientEphemeralPublicKeys(self, request, context):
    """Upload client ephemeral public keys for an associated token hash."""
    response = publisher_pb2.UploadClientEphemeralPublicKeysResponse

    invalid = self.handle_request_field_validation(
        context, request, response, ["token_hash", "client_ephemeral_public_key"]
    )
    if invalid:
        return invalid

    try:
        _validate_client_ephemeral_public_keys(request.client_ephemeral_public_key)

        with get_session() as s:
            token_hash_obj = (
                s.query(TokenHash)
                .filter(TokenHash.token_hash == request.token_hash)
                .first()
            )
            if not token_hash_obj:
                return self.handle_create_grpc_error_response(
                    context,
                    response,
                    "Token hash not found",
                    grpc.StatusCode.NOT_FOUND,
                )

            token = s.query(Token).filter(Token.id == token_hash_obj.token_id).first()
            if not token:
                return self.handle_create_grpc_error_response(
                    context,
                    response,
                    "Token not found",
                    grpc.StatusCode.NOT_FOUND,
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
                    for k in request.client_ephemeral_public_key
                ],
            )

        return response(
            success=True,
            message="Successfully uploaded keys",
            token_id=token.token_id,
        )

    except ValueError as exc:
        return self.handle_create_grpc_error_response(
            context,
            response,
            exc,
            grpc.StatusCode.INVALID_ARGUMENT,
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
