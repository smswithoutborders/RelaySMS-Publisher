# SPDX-License-Identifier: GPL-3.0-only
"""ExchangeOAuth2CodeAndStore gRPC service handler."""

import grpc
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey
from sqlalchemy import insert

from db import get_session
from grpc_services.v3.utils import get_oauth2_adapter
from logutils import get_logger
from models.server_ephemeral_key import ServerEphemeralKey
from models.token import create as create_token
from models.token_hash import create as create_token_hash
from platforms.adapter_ipc_handler import AdapterIPCHandler
from protos.v3 import publisher_pb2

logger = get_logger(__name__)


def ExchangeOAuth2CodeAndStore(self, request, context):
    """Exchange an OAuth2 authorization code for a token and persist it."""
    response = publisher_pb2.ExchangeOAuth2CodeAndStoreResponse

    invalid = self.handle_request_field_validation(
        context, request, response, ["platform", "authorization_code"]
    )
    if invalid:
        return invalid

    try:
        adapter = get_oauth2_adapter(request.platform)

        pipe = AdapterIPCHandler.invoke(
            adapter_path=adapter["path"],
            venv_path=adapter["venv_path"],
            method="exchange_code_and_fetch_user_info",
            params={
                "code": request.authorization_code,
                "code_verifier": request.code_verifier or None,
                "redirect_url": request.redirect_url or None,
                "request_identifier": request.request_identifier or None,
                "base_path": adapter["assets_path"],
            },
        )

        if pipe.get("error"):
            return self.handle_create_grpc_error_response(
                context,
                response,
                pipe["error"],
                grpc.StatusCode.INVALID_ARGUMENT,
                error_type="UNKNOWN",
            )

        result = pipe["result"]

        with get_session() as s:
            token = create_token(
                platform=request.platform.lower(),
                token_data={
                    "account_id": result["userinfo"]["account_identifier"],
                    "token": result["token"],
                },
                session=s,
            )

            token_hash = create_token_hash(token_id=token.id, session=s)

            keypairs = [X25519PrivateKey.generate() for _ in range(256)]
            s.execute(
                insert(ServerEphemeralKey),
                [
                    {
                        "token_hash_id": token_hash.id,
                        "key_index": i,
                        "private_key": kp.private_bytes_raw(),
                        "public_key": kp.public_key().public_bytes_raw(),
                        "used": False,
                    }
                    for i, kp in enumerate(keypairs)
                ],
            )

            s.flush()
            s.refresh(token_hash)
            server_keys = [
                publisher_pb2.PublicKey(key_id=k.key_index, public_key=k.public_key)
                for k in token_hash.server_keys.all()
            ]

        return response(
            success=True,
            message="Successfully fetched and stored token",
            account_identifier=result["userinfo"]["account_identifier"],
            server_ephemeral_public_key=server_keys,
            token_hash=token_hash.token_hash,
        )

    except NotImplementedError as exc:
        return self.handle_create_grpc_error_response(
            context,
            response,
            exc,
            grpc.StatusCode.UNIMPLEMENTED,
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
