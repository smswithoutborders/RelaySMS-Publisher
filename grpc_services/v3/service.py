# SPDX-License-Identifier: GPL-3.0-only
"""gRPC Publisher Service V3"""

import threading

import grpc
import sentry_sdk
from cachetools import TTLCache

from grpc_services.v3.exchange_oauth2_code import ExchangeOAuth2CodeAndStore
from grpc_services.v3.get_oauth2_auth_url import GetOAuth2AuthorizationUrl
from grpc_services.v3.revoke_oauth2_token import RevokeOAuth2Token
from grpc_services.v3.utils import verify_v1_request
from logutils import get_logger
from protos.v3 import publisher_pb2_grpc
from utils import get_configs

logger = get_logger(__name__)

NONCE_TTL_SECONDS = int(get_configs("NONCE_TTL_SECONDS", default_value="600"))


class PublisherServiceV3(publisher_pb2_grpc.PublisherServicer):
    """Publisher gRPC Service V3"""

    _nonce_cache: TTLCache = TTLCache(maxsize=10000, ttl=NONCE_TTL_SECONDS)
    _nonce_lock: threading.Lock = threading.Lock()

    GetOAuth2AuthorizationUrl = GetOAuth2AuthorizationUrl
    ExchangeOAuth2CodeAndStore = ExchangeOAuth2CodeAndStore
    RevokeOAuth2Token = RevokeOAuth2Token

    @classmethod
    def _get_nonce_lock(cls) -> threading.Lock:
        """Get the nonce lock for thread-safe nonce cache access."""
        return cls._nonce_lock

    def handle_v1_request_auth(
        self, context: grpc.ServicerContext, response
    ) -> tuple[bytes | None, object | None]:
        """Authenticate an incoming V1 encrypted request."""
        request_payload, error = verify_v1_request(
            context=context,
            nonce_cache=self._nonce_cache,
            nonce_lock=self._get_nonce_lock(),
            nonce_cache_ttl=NONCE_TTL_SECONDS,
        )
        if error:
            return None, self.handle_create_grpc_error_response(
                context=context,
                response=response,
                error=error,
                status_code=grpc.StatusCode.UNAUTHENTICATED,
                error_prefix="request authentication failed",
            )

        method_name = request_payload.method_name.decode()
        if method_name != context.method_name:
            logger.warning(
                "Request rejected -- method name %s does not match %s",
                method_name,
                context.method_name,
            )
            return None, self.handle_create_grpc_error_response(
                context=context,
                response=response,
                error="method name in payload does not match gRPC method",
                status_code=grpc.StatusCode.UNAUTHENTICATED,
                error_prefix="request authentication failed",
            )
        return request_payload.payload, None

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

        Returns None if all fields are present,
        or an error response on the first missing field.
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
