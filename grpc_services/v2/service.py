# SPDX-License-Identifier: GPL-3.0-only
"""gRPC Publisher Service V2"""

import json
import traceback

import grpc
import sentry_sdk

from grpc_services.v2.exchange_oauth2_code import ExchangeOAuth2CodeAndStore
from grpc_services.v2.exchange_pnba_code import ExchangePNBACodeAndStore
from grpc_services.v2.get_oauth2_auth_url import GetOAuth2AuthorizationUrl
from grpc_services.v2.get_pnba_code import GetPNBACode
from grpc_services.v2.revoke_oauth2_token import RevokeAndDeleteOAuth2Token
from grpc_services.v2.revoke_pnba_token import RevokeAndDeletePNBAToken
from logutils import get_logger
from protos.v2 import publisher_pb2_grpc
from vault_clients.v2.grpc_client import update_entity_token

logger = get_logger(__name__)


class PublisherServiceV2(publisher_pb2_grpc.PublisherServicer):
    """Publisher Service Descriptor V2"""

    def handle_create_grpc_error_response(
        self,
        context,
        response,
        error,
        status_code,
        send_to_sentry=False,
        user_msg=None,
        error_type="ERROR",
        error_prefix=None,
    ):
        """
        Handles the creation of a gRPC error response.

        Args:
            context (grpc.ServicerContext): The gRPC context object.
            response (callable): The gRPC response object.
            error (Exception or str): The exception instance or error message.
            status_code (grpc.StatusCode): The gRPC status code to be set for the response
                (e.g., grpc.StatusCode.INTERNAL).
            send_to_sentry (bool): If set to True, the error will be sent to Sentry for tracking.
            user_msg (str, optional): A user-friendly error message to be returned to the client.
                If not provided, the `error` message will be used.
            error_type (str, optional): A string identifying the type of error. Defaults to "ERROR".
                When set to "UNKNOWN", it triggers the logging of a full exception traceback
                for debugging purposes.
            error_prefix (str, optional): An optional prefix to prepend to the error message
                for additional context (e.g., indicating the specific operation or subsystem
                that caused the error).

        Returns:
            An instance of the specified response with the error set.
        """
        user_msg = user_msg or str(error)

        if error_type == "UNKNOWN" and isinstance(error, Exception):
            traceback.print_exception(type(error), error, error.__traceback__)
            if send_to_sentry:
                sentry_sdk.capture_exception(error)
        elif send_to_sentry:
            sentry_sdk.capture_message(user_msg, level="error")

        context.set_details(f"{error_prefix}: {user_msg}" if error_prefix else user_msg)
        context.set_code(status_code)

        return response()

    def handle_request_field_validation(
        self, context, request, response, required_fields
    ):
        """
        Validates the fields in the gRPC request.

        Args:
            context: gRPC context.
            request: gRPC request object.
            response: gRPC response object.
            required_fields (list): List of required fields, can include tuples.

        Returns:
            None or response: None if no missing fields,
                error response otherwise.
        """

        def validate_field(field):
            if not getattr(request, field, None):
                return self.handle_create_grpc_error_response(
                    context,
                    response,
                    f"Missing required field: {field}",
                    grpc.StatusCode.INVALID_ARGUMENT,
                )

            return None

        for field in required_fields:
            validation_error = validate_field(field)
            if validation_error:
                return validation_error

        return None

    def create_token_update_handler(self, response_cls, grpc_context, **kwargs):
        """
        Creates a function to handle updating the token for a specific device and account.

        Args:
            device_id (str): The unique identifier of the device.
            account_id (str): The identifier for the account (e.g., email or username).
            platform (str): The name of the platform (e.g., 'gmail').
            response_cls (protobuf message class): The response class for the gRPC method.
            grpc_context (grpc.ServicerContext): The gRPC context for the current method call.

        Returns:
            function: A function `handle_token_update(token)` that updates the token information.
        """
        device_id = kwargs.get("device_id")
        phone_number = kwargs.get("phone_number")
        account_id = kwargs["account_id"]
        platform = kwargs["platform"]
        skip_token_update = kwargs["skip_token_update"]

        def handle_token_update(token, **kwargs):
            """
            Handles updating the stored token for the specified device and account.

            Args:
                token (dict or object): The token information containing access and refresh tokens.
            """
            logger.debug(kwargs)
            if skip_token_update:
                logger.debug("Skipping token update for %s on %s", account_id, platform)
                return True

            update_response, update_error = update_entity_token(
                device_id=device_id,
                phone_number=phone_number,
                token=json.dumps(token),
                account_identifier=account_id,
                platform=platform,
            )

            if update_error:
                return self.handle_create_grpc_error_response(
                    grpc_context,
                    response_cls,
                    update_error.details(),
                    update_error.code(),
                )

            if not update_response.success:
                return response_cls(
                    message=update_response.message,
                    success=update_response.success,
                )

            return True

        return handle_token_update

    def get_metadata(self, context):
        """Extracts metadata from the gRPC context."""
        metadata = list(context.invocation_metadata())
        metadata.append(("x-method-name", context.method_name))
        return metadata

    GetOAuth2AuthorizationUrl = GetOAuth2AuthorizationUrl
    ExchangeOAuth2CodeAndStore = ExchangeOAuth2CodeAndStore
    RevokeAndDeleteOAuth2Token = RevokeAndDeleteOAuth2Token
    GetPNBACode = GetPNBACode
    ExchangePNBACodeAndStore = ExchangePNBACodeAndStore
    RevokeAndDeletePNBAToken = RevokeAndDeletePNBAToken
