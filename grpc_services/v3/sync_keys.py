# SPDX-License-Identifier: GPL-3.0-only
"""SyncKeys gRPC service handler."""

import hashlib
import secrets

import grpc

from db import get_session
from grpc_services.v3.utils import (
    get_keys_for_decryption,
    sync_token_pools,
    validate_client_ephemeral_public_keys,
)
from lib_relaysms_payload_specs.generated import relaysms_spec_payload as rrs
from logutils import get_logger
from models.server_identity_key import mark_key_used as mark_ss_key_used
from protos.v3 import publisher_pb2

logger = get_logger(__name__)


def SyncKeys(self, request, context):
    """Handles SyncKeys."""
    response = publisher_pb2.SyncKeysResponse

    payload_bin, auth_error = self.handle_v1_request_auth(context, response)
    if auth_error:
        return auth_error

    invalid = self.handle_request_field_validation(
        context,
        request,
        response,
        ["token_id", "key_id", "client_ephemeral_public_keys"],
    )
    if invalid:
        return invalid

    try:
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

        with get_session() as s:
            _, token_hash_obj, ss_kid, es_kid, _, ec_kid_pk = get_keys_for_decryption(
                token_id=request.token_id, key_id=request.key_id, session=s
            )

            try:
                decrypted_token = rrs.v1_token_decrypt_server(
                    ss_kid=ss_kid,
                    es_kid=es_kid,
                    ec_kid_pk=ec_kid_pk,
                    key_id=request.key_id,
                    ciphertext=payload_bin,
                )
            except rrs.V1CryptographicError.FailedToDecrypt as e:
                return self.handle_create_grpc_error_response(
                    context,
                    response,
                    f"token decryption failed: {e}",
                    grpc.StatusCode.UNAUTHENTICATED,
                )

            if not secrets.compare_digest(
                hashlib.sha256(decrypted_token).digest(), token_hash_obj.token_hash
            ):
                return self.handle_create_grpc_error_response(
                    context,
                    response,
                    "token hash mismatch",
                    grpc.StatusCode.UNAUTHENTICATED,
                )

            mark_ss_key_used(request.key_id, s)

            server_public_keys = sync_token_pools(
                token_hash_obj=token_hash_obj,
                client_ephemeral_public_keys=request.client_ephemeral_public_keys,
                session=s,
            )

        return response(
            success=True,
            message="Successfully synced keys",
            server_ephemeral_public_keys=server_public_keys,
        )

    except ValueError as exc:
        return self.handle_create_grpc_error_response(
            context, response, exc, grpc.StatusCode.NOT_FOUND
        )

    except NotImplementedError as exc:
        return self.handle_create_grpc_error_response(
            context, response, exc, grpc.StatusCode.UNIMPLEMENTED
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
