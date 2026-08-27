# SPDX-License-Identifier: GPL-3.0-only
"""RevokePNBAToken gRPC service handler."""

import hashlib
import secrets

import grpc

from db import get_session
from keys import KeyManager, KeyManagerError
from lib_relaysms_payload_specs.generated import relaysms_spec_payload as rrs
from logutils import get_logger
from protos.v3 import publisher_pb2
from token_revocation import revoke_pnba_token_upstream

logger = get_logger(__name__)


def RevokePNBAToken(self, request, context):
    """Handles RevokePNBAToken."""
    response = publisher_pb2.RevokePNBATokenResponse

    payload_bin, auth_error = self.handle_v1_request_auth(context, response)
    if auth_error:
        return auth_error

    if not payload_bin:
        logger.error("Missing token ciphertext in revoke request")
        return self.handle_create_grpc_error_response(
            context,
            response,
            "token ciphertext is required in the request payload",
            grpc.StatusCode.INVALID_ARGUMENT,
        )

    invalid = self.handle_request_field_validation(
        context, request, response, ["token_id", "key_id"]
    )
    if invalid:
        return invalid

    try:
        with get_session() as s:
            key_manager = KeyManager(s)
            token, token_hash_obj, ss_kid, es_kid, _, ec_kid_pk = (
                key_manager.get_token_and_keys_for_decryption(
                    token_id=request.token_id, key_id=request.key_id
                )
            )

            try:
                decrypted_token = rrs.v1_token_decrypt_server(
                    ss_kid=ss_kid,
                    es_kid=es_kid,
                    ec_kid_pk=ec_kid_pk,
                    key_id=request.key_id,
                    ciphertext=payload_bin,
                )
            except rrs.V1CryptographicError.FailedToDecrypt:
                logger.exception("Token decryption failed: kid=%s", request.key_id)
                return self.handle_create_grpc_error_response(
                    context,
                    response,
                    "revocation failed",
                    grpc.StatusCode.UNAUTHENTICATED,
                )

            if not secrets.compare_digest(
                hashlib.sha256(decrypted_token).digest(), token_hash_obj.token_hash
            ):
                logger.error("Token hash mismatch: kid=%s", request.key_id)
                return self.handle_create_grpc_error_response(
                    context,
                    response,
                    "revocation failed",
                    grpc.StatusCode.UNAUTHENTICATED,
                )

            error = revoke_pnba_token_upstream(token, self.adapter_manager)
            if error:
                logger.error(
                    "Adapter revocation failed for platform %r: %s",
                    token.platform,
                    error,
                )

            s.delete(token)
            key_manager.mark_identity_key_used(request.key_id)
            logger.info("Token revoked: platform=%r", token.platform)

        return response(success=True, message="Successfully revoked and deleted token")

    except NotImplementedError as exc:
        return self.handle_create_grpc_error_response(
            context, response, exc, grpc.StatusCode.UNIMPLEMENTED
        )

    except KeyManagerError:
        return self.handle_create_grpc_error_response(
            context, response, "revocation failed", grpc.StatusCode.UNAUTHENTICATED
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
