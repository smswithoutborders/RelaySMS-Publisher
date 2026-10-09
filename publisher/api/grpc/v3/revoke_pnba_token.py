# SPDX-License-Identifier: GPL-3.0-only
"""RevokePNBAToken handler."""

import logging

from grpc_interceptor.exceptions import InvalidArgument, Unauthenticated

from protos.v3 import publisher_pb2
from publisher import keys, tokens
from publisher.db import get_session
from publisher.models.server_identity_key import mark_key_used

logger = logging.getLogger(__name__)


def revoke_pnba_token(request, payload: bytes) -> publisher_pb2.RevokePNBATokenResponse:
    if not payload:
        raise InvalidArgument("token ciphertext is required in the request payload")

    with get_session() as s:
        try:
            token = keys.verify_token(s, request.token_id, request.key_id, payload)
        except keys.KeyManagementError:
            raise Unauthenticated("revocation failed") from None

        revocation = tokens.revocation(s, token)
        s.delete(token)
        mark_key_used(s, request.key_id)
        logger.info("Token revoked: platform=%r", token.platform)
    tokens.revoke_upstream(revocation)

    return publisher_pb2.RevokePNBATokenResponse(
        success=True, message="Successfully revoked and deleted token"
    )
