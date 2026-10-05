# SPDX-License-Identifier: GPL-3.0-only
"""RevokePNBAToken handler."""

import logging

from grpc_interceptor.exceptions import InvalidArgument, Unauthenticated

from protos.v3 import publisher_pb2
from publisher import keys
from publisher.api.grpc.utils import require_fields
from publisher.db import get_session
from publisher.models.server_identity_key import mark_key_used
from publisher.platforms.manager import AdapterManager
from publisher.tokens import revoke_pnba_token_upstream

logger = logging.getLogger(__name__)


def revoke_pnba_token(
    request, payload: bytes, adapter_manager: AdapterManager
) -> publisher_pb2.RevokePNBATokenResponse:
    if not payload:
        raise InvalidArgument("token ciphertext is required in the request payload")
    require_fields(request, "token_id", "key_id")

    with get_session() as s:
        try:
            token = keys.verify_token(s, request.token_id, request.key_id, payload)
        except keys.KeyManagementError:
            raise Unauthenticated("revocation failed") from None

        error = revoke_pnba_token_upstream(token, adapter_manager)
        if error:
            logger.error(
                "Adapter revocation failed for platform %r: %s", token.platform, error
            )

        s.delete(token)
        mark_key_used(s, request.key_id)
        logger.info("Token revoked: platform=%r", token.platform)

    return publisher_pb2.RevokePNBATokenResponse(
        success=True, message="Successfully revoked and deleted token"
    )
