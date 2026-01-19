# SPDX-License-Identifier: GPL-3.0-only
"""Revoke OAuth2 Token gRPC Service Implementation"""

import json

import grpc

from logutils import get_logger
from platforms.adapter_ipc_handler import AdapterIPCHandler
from platforms.adapter_manager import AdapterManager
from protos.v1 import publisher_pb2
from vault_clients.v1.grpc_client import delete_entity_token, get_entity_access_token

logger = get_logger(__name__)


def RevokeAndDeleteOAuth2Token(self, request, context):
    """Handles revoking and deleting OAuth2 access tokens"""

    response = publisher_pb2.RevokeAndDeleteOAuth2TokenResponse
    return self.handle_deprecated_v1_method(context, response)

    def validate_fields():
        return self.handle_request_field_validation(
            context,
            request,
            response,
            ["long_lived_token", "platform", "account_identifier"],
        )

    def get_access_token():
        get_access_token_response, get_access_token_error = get_entity_access_token(
            platform=request.platform,
            account_identifier=request.account_identifier,
            long_lived_token=request.long_lived_token,
        )
        if get_access_token_error:
            return None, self.handle_create_grpc_error_response(
                context,
                response,
                get_access_token_error.details(),
                get_access_token_error.code(),
            )
        if not get_access_token_response.success:
            return None, response(
                message=get_access_token_response.message,
                success=get_access_token_response.success,
            )
        return get_access_token_response.token, None

    def delete_token():
        delete_token_response, delete_token_error = delete_entity_token(
            request.long_lived_token, request.platform, request.account_identifier
        )

        if delete_token_error:
            return self.handle_create_grpc_error_response(
                context,
                response,
                delete_token_error.details(),
                delete_token_error.code(),
            )

        if not delete_token_response.success:
            return response(
                message=delete_token_response.message,
                success=delete_token_response.success,
            )

        return response(success=True, message="Successfully deleted token")

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

        access_token, access_token_error = get_access_token()
        if access_token_error:
            return access_token_error

        params = {"token": json.loads(access_token)}

        pipe = AdapterIPCHandler.invoke(
            adapter_path=adapter["path"],
            venv_path=adapter["venv_path"],
            method="revoke_token",
            params=params,
        )

        if pipe.get("error"):
            logger.error(pipe.get("error"))

        return delete_token()

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
