# SPDX-License-Identifier: GPL-3.0-only
"""RevokeOAuth2Token gRPC service handler."""

import hashlib
import secrets

import grpc

from db import get_session
from grpc_services.v3.utils import get_keys_for_decryption, get_oauth2_adapter
from lib_relaysms_payload_specs.generated import relaysms_spec_payload as rrs
from logutils import get_logger
from models.server_identity_key import mark_key_used as mark_ss_key_used
from platforms.adapter_ipc_handler import AdapterIPCHandler
from protos.v3 import publisher_pb2

logger = get_logger(__name__)


def RevokeOAuth2Token(self, request, context):
    """Handles RevokeOAuth2Token."""
    response = publisher_pb2.RevokeOAuth2TokenResponse

    payload_bin, auth_error = self.handle_v1_request_auth(context, response)
    if auth_error:
        return auth_error

    invalid = self.handle_request_field_validation(
        context, request, response, ["token_id", "key_id"]
    )
    if invalid:
        return invalid

    try:
        with get_session() as s:
            token, token_hash_obj, ss_kid, es_kid, _, ec_kid_pk = (
                get_keys_for_decryption(
                    token_id=request.token_id, key_id=request.key_id, session=s
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

            adapter = get_oauth2_adapter(self.adapter_manager, token.platform)

            pipe = AdapterIPCHandler.invoke(
                adapter_path=adapter.path,
                venv_path=adapter.venv_path,
                method="revoke_token",
                params={
                    "token": token.token_data["token"],
                    "base_path": adapter.assets_path,
                },
            )

            if pipe.get("error"):
                logger.error("adapter revocation failed: %s", pipe["error"])

            s.delete(token)
            mark_ss_key_used(request.key_id, s)

        return response(success=True, message="Successfully revoked and deleted token")

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
