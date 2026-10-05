# SPDX-License-Identifier: GPL-3.0-only
"""ExchangeOAuth2CodeAndStore handler."""

from db import get_session
from grpc_services.utils import (
    call_adapter,
    require_fields,
    validate_client_ephemeral_public_keys,
)
from keys import KeyManager
from models.token import create as create_token
from platforms.adapter_manager import AdapterManager
from protos.v3 import publisher_pb2


def exchange_oauth2_code_and_store(
    request, adapter_manager: AdapterManager
) -> publisher_pb2.ExchangeOAuth2CodeAndStoreResponse:
    require_fields(
        request, "platform", "authorization_code", "client_ephemeral_public_keys"
    )
    validate_client_ephemeral_public_keys(request.client_ephemeral_public_keys)

    adapter = adapter_manager.get_oauth2_adapter(request.platform)
    result = call_adapter(
        adapter,
        "exchange_code_and_fetch_user_info",
        {
            "code": request.authorization_code,
            "code_verifier": request.code_verifier or None,
            "redirect_url": request.redirect_url or None,
            "request_identifier": request.request_identifier or None,
            "base_path": adapter.assets_path,
        },
    )
    account_identifier = result["userinfo"]["account_identifier"]

    with get_session() as s:
        token = create_token(
            platform=request.platform.lower(),
            cat_id=adapter.cat_id,
            proto_id=adapter.proto_id,
            token_data={"account_id": account_identifier, "token": result["token"]},
            session=s,
        )
        key_manager = KeyManager(s)
        token_ciphertext, kid_index, server_public_keys = (
            key_manager.create_token_pools_and_encrypt(
                token_pk_id=token.id,
                client_public_keys=request.client_ephemeral_public_keys,
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
