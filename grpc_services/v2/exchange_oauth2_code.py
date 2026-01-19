# SPDX-License-Identifier: GPL-3.0-only
"""Exchange OAuth2 Authorization Code gRPC Service Implementation"""

import json

import grpc

from platforms.adapter_ipc_handler import AdapterIPCHandler
from platforms.adapter_manager import AdapterManager
from protos.v2 import publisher_pb2
from vault_clients.v2.grpc_client import list_entity_stored_tokens, store_entity_token


def ExchangeOAuth2CodeAndStore(self, request, context):
    """Handles exchanging OAuth2 authorization code for a token"""

    response = publisher_pb2.ExchangeOAuth2CodeAndStoreResponse
    metadata = self.get_metadata(context)

    def validate_fields():
        return self.handle_request_field_validation(
            context, request, response, ["platform", "authorization_code"]
        )

    def list_tokens():
        list_response, list_error = list_entity_stored_tokens(metadata=metadata)
        if list_error:
            return None, self.handle_create_grpc_error_response(
                context,
                response,
                list_error.details(),
                list_error.code(),
                error_type="UNKNOWN",
            )
        return list_response, None

    def store_token(token, userinfo):
        local_tokens = {}

        if request.store_on_device:
            local_tokens = {
                "access_token": token.pop("access_token"),
                "refresh_token": token.pop("refresh_token"),
                "id_token": token.pop("id_token", ""),
            }

        store_response, store_error = store_entity_token(
            platform=request.platform,
            account_identifier=userinfo.get("account_identifier"),
            token=json.dumps(token),
            metadata=metadata,
        )

        if store_error:
            return self.handle_create_grpc_error_response(
                context,
                response,
                store_error.details(),
                store_error.code(),
                error_type="UNKNOWN",
            )

        if not store_response.success:
            return response(
                message=store_response.message, success=store_response.success
            )

        return response(
            success=True,
            message="Successfully fetched and stored token",
            tokens=local_tokens,
        )

    try:
        invalid_fields_response = validate_fields()
        if invalid_fields_response:
            return invalid_fields_response

        adapter = AdapterManager.get_adapter_path(
            name=request.platform.lower(), protocol="oauth2"
        )
        if not adapter:
            raise NotImplementedError(
                f"The platform '{request.platform.lower()}' with "
                "protocol 'oauth2' is currently not supported. "
                "Please contact the developers for more information on when "
                "this platform will be implemented."
            )

        _, token_list_error = list_tokens()
        if token_list_error:
            return token_list_error

        params = {
            "code": request.authorization_code,
            "code_verifier": getattr(request, "code_verifier") or None,
            "redirect_url": getattr(request, "redirect_url") or None,
            "request_identifier": getattr(request, "request_identifier") or None,
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
                pipe.get("error"),
                grpc.StatusCode.INVALID_ARGUMENT,
                error_type="UNKNOWN",
            )

        result = pipe.get("result")

        return store_token(token=result.get("token"), userinfo=result.get("userinfo"))

    except NotImplementedError as e:
        return self.handle_create_grpc_error_response(
            context,
            response,
            str(e),
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
