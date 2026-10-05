# SPDX-License-Identifier: GPL-3.0-only
"""ExchangePNBACodeAndStore handler."""

from protos.v3 import publisher_pb2
from publisher import keys
from publisher.api.grpc.utils import (
    call_adapter,
    require_fields,
    validate_client_ephemeral_public_keys,
)
from publisher.db import get_session
from publisher.models.token import create as create_token
from publisher.platforms.manager import AdapterManager


def exchange_pnba_code_and_store(
    request, adapter_manager: AdapterManager
) -> publisher_pb2.ExchangePNBACodeAndStoreResponse:
    require_fields(
        request,
        "platform",
        "phone_number",
        "authorization_code",
        "client_ephemeral_public_keys",
    )
    validate_client_ephemeral_public_keys(request.client_ephemeral_public_keys)

    adapter = adapter_manager.get_pnba_adapter(request.platform)
    result = call_adapter(
        adapter,
        (
            "validate_password_and_fetch_user_info"
            if request.password
            else "validate_code_and_fetch_user_info"
        ),
        {
            "code": request.authorization_code,
            "phone_number": request.phone_number,
            "base_path": adapter.assets_path,
            "password": request.password or None,
            "request_identifier": request.request_identifier or None,
            "channel": request.channel or None,
        },
    )

    if result.get("two_step_verification_enabled"):
        return publisher_pb2.ExchangePNBACodeAndStoreResponse(
            success=True,
            two_step_verification_enabled=True,
            platform=adapter.name,
            cat_id=adapter.cat_id,
            message="two-steps verification is enabled and a password is required",
        )

    account_identifier = result["userinfo"]["account_identifier"]

    with get_session() as s:
        token = create_token(
            s,
            platform=request.platform.lower(),
            cat_id=adapter.cat_id,
            proto_id=adapter.proto_id,
            token_data={"account_id": account_identifier, "token": result["session"]},
        )
        token_ciphertext, kid_index, server_public_keys = (
            keys.create_token_pools_and_encrypt(
                s, token.id, request.client_ephemeral_public_keys
            )
        )

    return publisher_pb2.ExchangePNBACodeAndStoreResponse(
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
