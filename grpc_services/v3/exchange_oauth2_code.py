# SPDX-License-Identifier: GPL-3.0-only
"""ExchangeOAuth2CodeAndStore gRPC service handler."""

import grpc

from grpc_services.v3.utils import get_oauth2_adapter
from key_generation import initialize_token_hash_with_keys
from logutils import get_logger
from models.token import create as create_token
from platforms.adapter_ipc_handler import AdapterIPCHandler
from protos.v3 import publisher_pb2

logger = get_logger(__name__)


def _store_token(platform: str, token: dict, userinfo: dict, response):
    """Persist the token and return a fully populated gRPC response."""
    account_id = userinfo["account_identifier"]
    token_obj = create_token(
        platform=platform, token_data={"account_id": account_id, "token": token}
    )
    token_hash_obj, server_keys = initialize_token_hash_with_keys(token_id=token_obj.id)

    return response(
        success=True,
        message="Successfully fetched and stored token",
        account_identifier=account_id,
        server_ephemeral_public_key=server_keys,
        token_hash=token_hash_obj.token_hash,
    )


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

        params = {
            "code": request.authorization_code,
            "code_verifier": request.code_verifier or None,
            "redirect_url": request.redirect_url or None,
            "request_identifier": request.request_identifier or None,
            "base_path": adapter["assets_path"],
        }

        pipe = AdapterIPCHandler.invoke(
            adapter_path=adapter["path"],
            venv_path=adapter["venv_path"],
            method="exchange_code_and_fetch_user_info",
            params=params,
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
        return _store_token(
            platform=request.platform.lower(),
            token=result["token"],
            userinfo=result["userinfo"],
            response=response,
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
