# SPDX-License-Identifier: GPL-3.0-only
"""RevokeOAuth2Token handler."""

import logging

from grpc_interceptor.exceptions import InvalidArgument, Unauthenticated

from protos.v3 import publisher_pb2
from publisher import keys
from publisher.db import get_session
from publisher.models.server_identity_key import mark_key_used
from publisher.platforms.manager import AdapterManager
from publisher.tokens import revoke_oauth2_token_upstream

logger = logging.getLogger(__name__)


def revoke_oauth2_token(
    request, payload: bytes, adapter_manager: AdapterManager
) -> publisher_pb2.RevokeOAuth2TokenResponse:
    if not payload:
        raise InvalidArgument("token ciphertext is required in the request payload")

    with get_session() as s:
        try:
            token = keys.verify_token(s, request.token_id, request.key_id, payload)
        except keys.KeyManagementError:
            raise Unauthenticated("revocation failed") from None

        error = revoke_oauth2_token_upstream(token, adapter_manager)
        if error:
            logger.error(
                "Adapter revocation failed for platform %r: %s", token.platform, error
            )

        s.delete(token)
        mark_key_used(s, request.key_id)
        logger.info("Token revoked: platform=%r", token.platform)

    return publisher_pb2.RevokeOAuth2TokenResponse(
        success=True, message="Successfully revoked and deleted token"
    )
