# SPDX-License-Identifier: GPL-3.0-only
"""Exchange PNBA code gRPC service implementation."""

import json

import grpc

from platforms.adapter_ipc_handler import AdapterIPCHandler
from platforms.adapter_manager import AdapterManager
from protos.v1 import publisher_pb2
from vault_clients.v1.grpc_client import list_entity_stored_tokens, store_entity_token


def ExchangePNBACodeAndStore(self, request, context):
    """Handles Exchanging Phone number-based Authentication code for access."""

    response = publisher_pb2.ExchangePNBACodeAndStoreResponse
    return self.handle_deprecated_v1_method(context, response)

    def validate_fields():
        return self.handle_request_field_validation(
            context,
            request,
            response,
            ["long_lived_token", "phone_number", "platform", "authorization_code"],
        )

    def list_tokens():
        list_response, list_error = list_entity_stored_tokens(
            long_lived_token=request.long_lived_token
        )
        if list_error:
            return None, self.handle_create_grpc_error_response(
                context,
                response,
                list_error.details(),
                list_error.code(),
                error_type="UNKNOWN",
            )
        return list_response, None

    def store_token(userinfo):
        store_response, store_error = store_entity_token(
            long_lived_token=request.long_lived_token,
            platform=request.platform,
            account_identifier=userinfo.get("account_identifier"),
            token=json.dumps(userinfo.get("account_identifier")),
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

        return response(success=True, message="Successfully fetched and stored token")

    try:
        invalid_fields_response = validate_fields()
        if invalid_fields_response:
            return invalid_fields_response

        adapter = AdapterManager.get_adapter_path(
            name=request.platform.lower(), protocol="pnba"
        )
        if not adapter:
            raise NotImplementedError(
                f"The platform '{request.platform.lower()}' with "
                "protocol 'pnba' is currently not supported. "
                "Please contact the developers for more information on when "
                "this platform will be implemented."
            )

        _, token_list_error = list_tokens()
        if token_list_error:
            return token_list_error

        params = {
            "code": request.authorization_code,
            "phone_number": request.phone_number,
            "base_path": adapter["assets_path"],
            "password": getattr(request, "password") or None,
            "request_identifier": getattr(request, "request_identifier") or None,
        }

        if params.get("password"):
            pipe = AdapterIPCHandler.invoke(
                adapter_path=adapter["path"],
                venv_path=adapter["venv_path"],
                method="validate_password_and_fetch_user_info",
                params=params,
            )
        else:
            pipe = AdapterIPCHandler.invoke(
                adapter_path=adapter["path"],
                venv_path=adapter["venv_path"],
                method="validate_code_and_fetch_user_info",
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
        if result.get("two_step_verification_enabled"):
            return response(
                success=True,
                two_step_verification_enabled=True,
                message="two-steps verification is enabled and a password is required",
            )

        return store_token(userinfo=result.get("userinfo"))

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
