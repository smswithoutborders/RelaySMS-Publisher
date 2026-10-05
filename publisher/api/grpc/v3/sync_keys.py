# SPDX-License-Identifier: GPL-3.0-only
"""SyncKeys handler."""

import logging

from grpc_interceptor.exceptions import InvalidArgument, Unauthenticated

from protos.v3 import publisher_pb2
from publisher import keys
from publisher.api.grpc.utils import (
    require_fields,
    validate_client_ephemeral_public_keys,
)
from publisher.db import get_session
from publisher.models.server_identity_key import mark_key_used
from publisher.models.token_hash import update_last_used as mark_token_hash_used

logger = logging.getLogger(__name__)


def sync_keys(request, payload: bytes) -> publisher_pb2.SyncKeysResponse:
    if not payload:
        raise InvalidArgument("token ciphertext is required in the request payload")
    require_fields(request, "token_id", "key_id", "client_ephemeral_public_keys")
    validate_client_ephemeral_public_keys(request.client_ephemeral_public_keys)

    with get_session() as s:
        try:
            token = keys.verify_token(s, request.token_id, request.key_id, payload)
        except keys.KeyManagementError:
            raise Unauthenticated("sync failed") from None

        mark_key_used(s, request.key_id)
        server_public_keys = keys.sync_token_pools(
            s, token.token_hash, request.client_ephemeral_public_keys
        )
        mark_token_hash_used(s, token.token_hash)
        logger.info("Successfully synced keys for token_id=%s", request.token_id)

    return publisher_pb2.SyncKeysResponse(
        success=True,
        message="Successfully synced keys",
        server_ephemeral_public_keys=[
            publisher_pb2.PublicKey(key_id=i, public_key=pk)
            for i, pk in enumerate(server_public_keys)
        ],
    )
