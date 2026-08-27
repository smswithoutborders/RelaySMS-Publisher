# SPDX-License-Identifier: GPL-3.0-only
"""SyncKeys gRPC service handler."""

import hashlib
import secrets

import grpc

from db import get_session
from grpc_services.v3.utils import (
    sync_token_pools,
    validate_client_ephemeral_public_keys,
)
from keys import KeyManager, KeyManagerError
from lib_relaysms_payload_specs.generated import relaysms_spec_payload as rrs
from logutils import get_logger
from models.token_hash import update_last_used as mark_token_hash_used
from protos.v3 import publisher_pb2

logger = get_logger(__name__)


def SyncKeys(self, request, context):
    """Handles SyncKeys."""
    response = publisher_pb2.SyncKeysResponse

    payload_bin, auth_error = self.handle_v1_request_auth(context, response)
    if auth_error:
        return auth_error

    if not payload_bin:
        logger.error("Missing token ciphertext in sync request")
        return self.handle_create_grpc_error_response(
            context,
            response,
            "token ciphertext is required in the request payload",
            grpc.StatusCode.INVALID_ARGUMENT,
        )

    invalid = self.handle_request_field_validation(
        context,
        request,
        response,
        ["token_id", "key_id", "client_ephemeral_public_keys"],
    )
    if invalid:
        return invalid

    validation_error = validate_client_ephemeral_public_keys(
        request.client_ephemeral_public_keys
    )
    if validation_error:
        return self.handle_create_grpc_error_response(
            context,
            response,
            validation_error,
            grpc.StatusCode.INVALID_ARGUMENT,
        )

    try:
        with get_session() as s:
            key_manager = KeyManager(s)
            _, token_hash_obj, ss_kid, es_kid, _, ec_kid_pk = (
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
            except rrs.V1CryptographicError.FailedToDecrypt as exc:
                logger.exception("Token decryption failed: kid=%s", request.key_id)
                return self.handle_create_grpc_error_response(
                    context,
                    response,
                    "sync failed",
                    grpc.StatusCode.UNAUTHENTICATED,
                )

            if not secrets.compare_digest(
                hashlib.sha256(decrypted_token).digest(), token_hash_obj.token_hash
            ):
                logger.error("Token hash mismatch: kid=%s", request.key_id)
                return self.handle_create_grpc_error_response(
                    context,
                    response,
                    "sync failed",
                    grpc.StatusCode.UNAUTHENTICATED,
                )

            key_manager.mark_identity_key_used(request.key_id)
            server_public_keys = sync_token_pools(
                token_hash_obj=token_hash_obj,
                client_ephemeral_public_keys=request.client_ephemeral_public_keys,
                session=s,
            )
            mark_token_hash_used(token_hash_obj, s)
            logger.info("Successfully synced keys for token_id=%s", request.token_id)

        return response(
            success=True,
            message="Successfully synced keys",
            server_ephemeral_public_keys=server_public_keys,
        )

    except NotImplementedError as exc:
        return self.handle_create_grpc_error_response(
            context, response, exc, grpc.StatusCode.UNIMPLEMENTED
        )

    except KeyManagerError:
        return self.handle_create_grpc_error_response(
            context, response, "sync failed", grpc.StatusCode.UNAUTHENTICATED
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
