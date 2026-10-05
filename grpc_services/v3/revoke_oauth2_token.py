# SPDX-License-Identifier: GPL-3.0-only
"""RevokeOAuth2Token handler."""

import logging

from grpc_interceptor.exceptions import InvalidArgument, Unauthenticated

from grpc_services.utils import require_fields
from keys import KeyManager, KeyManagerError
from platforms.adapter_manager import AdapterManager
from protos.v3 import publisher_pb2
from publisher.db import get_session
from token_revocation import revoke_oauth2_token_upstream

logger = logging.getLogger(__name__)


def revoke_oauth2_token(
    request, payload: bytes, adapter_manager: AdapterManager
) -> publisher_pb2.RevokeOAuth2TokenResponse:
    if not payload:
        raise InvalidArgument("token ciphertext is required in the request payload")
    require_fields(request, "token_id", "key_id")

    with get_session() as s:
        key_manager = KeyManager(s)
        try:
            token = key_manager.verify_token(request.token_id, request.key_id, payload)
        except KeyManagerError:
            raise Unauthenticated("revocation failed") from None

        error = revoke_oauth2_token_upstream(token, adapter_manager)
        if error:
            logger.error(
                "Adapter revocation failed for platform %r: %s", token.platform, error
            )

        s.delete(token)
        key_manager.mark_identity_key_used(request.key_id)
        logger.info("Token revoked: platform=%r", token.platform)

    return publisher_pb2.RevokeOAuth2TokenResponse(
        success=True, message="Successfully revoked and deleted token"
    )
