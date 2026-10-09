# SPDX-License-Identifier: GPL-3.0-only
"""ExchangeOAuth2CodeAndStore handler."""

from protos.v3 import publisher_pb2
from publisher import keys
from publisher.api.grpc.utils import (
    call_adapter,
    find_adapter,
    require_fields,
    validate_client_ephemeral_public_keys,
)
from publisher.db import get_session
from publisher.models.platform_adapter import OAUTH2
from publisher.models.token import create as create_token


def exchange_oauth2_code_and_store(
    request,
) -> publisher_pb2.ExchangeOAuth2CodeAndStoreResponse:
    require_fields(
        request, "platform", "authorization_code", "client_ephemeral_public_keys"
    )
    validate_client_ephemeral_public_keys(request.client_ephemeral_public_keys)

    adapter = find_adapter(request.platform, OAUTH2)
    result = call_adapter(
        adapter,
        "exchange_code_and_fetch_user_info",
        {
            "code": request.authorization_code,
            "code_verifier": request.code_verifier or None,
            "redirect_url": request.redirect_url or None,
            "request_identifier": request.request_identifier or None,
            "base_path": adapter.state_path,
        },
    )
    account_identifier = result["userinfo"]["account_identifier"]

    with get_session() as s:
        token = create_token(
            s,
            platform=request.platform.lower(),
            cat_id=adapter.cat_id,
            proto_id=adapter.proto_id,
            token_data={"account_id": account_identifier, "token": result["token"]},
        )
        token_ciphertext, kid_index, server_public_keys = (
            keys.create_token_pools_and_encrypt(
                s, token.id, request.client_ephemeral_public_keys
            )
        )

    return publisher_pb2.ExchangeOAuth2CodeAndStoreResponse(
        success=True,
        message="Successfully fetched and stored token",
        account_identifier=account_identifier,
        token_ciphertext=token_ciphertext,
        token_id=token.token_id,
        server_ephemeral_public_keys=[
            publisher_pb2.PublicKey(key_id=i, public_key=pk)
            for i, pk in enumerate(server_public_keys)
        ],
        key_id=kid_index,
        platform=adapter.name,
        cat_id=adapter.cat_id,
    )
