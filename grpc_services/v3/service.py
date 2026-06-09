# SPDX-License-Identifier: GPL-3.0-only
"""gRPC Publisher Service V3"""

import grpc
import sentry_sdk

from grpc_services.v3.exchange_oauth2_code import ExchangeOAuth2CodeAndStore
from grpc_services.v3.get_oauth2_auth_url import GetOAuth2AuthorizationUrl
from logutils import get_logger
from protos.v3 import publisher_pb2_grpc

logger = get_logger(__name__)


class PublisherServiceV3(publisher_pb2_grpc.PublisherServicer):
    """Publisher gRPC Service V3"""

    GetOAuth2AuthorizationUrl = GetOAuth2AuthorizationUrl
    ExchangeOAuth2CodeAndStore = ExchangeOAuth2CodeAndStore

    def handle_create_grpc_error_response(
        self,
        context,
        response,
        error,
        status_code,
        send_to_sentry: bool = False,
        user_msg: str = None,
        error_type: str = "ERROR",
        error_prefix: str = None,
    ):
        """Create and return a gRPC error response.

        Args:
            context: gRPC servicer context.
            response: gRPC response class.
            error: Exception instance or error message string.
            status_code: gRPC status code (e.g. grpc.StatusCode.INTERNAL).
            send_to_sentry: Forward the error to Sentry if True.
            user_msg: Client-facing message. Falls back to str(error).
            error_type: Set to "UNKNOWN" to log a full traceback.
            error_prefix: Prepended to the client message for context.
        """
        user_msg = user_msg or str(error)

        if error_type == "UNKNOWN" and isinstance(error, Exception):
            logger.exception(error)
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
        """Validate required fields on a gRPC request.

        Returns None if all fields are present, or an error response on the first missing field.
        """
        for field in required_fields:
            if not getattr(request, field, None):
                return self.handle_create_grpc_error_response(
                    context,
                    response,
                    f"Missing required field: {field}",
                    grpc.StatusCode.INVALID_ARGUMENT,
                )
        return None
