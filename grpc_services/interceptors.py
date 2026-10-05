# SPDX-License-Identifier: GPL-3.0-only
"""Interceptors for the Publisher gRPC server."""

import threading
import time
from contextvars import ContextVar

import grpc
from cachetools import TTLCache
from grpc_interceptor import ExceptionToStatusInterceptor, ServerInterceptor
from grpc_interceptor.exceptions import (
    GrpcException,
    Internal,
    Unauthenticated,
    Unimplemented,
)
from opentelemetry import trace as otel_trace

from db import get_session
from lib_relaysms_payload_specs.generated import relaysms_spec_payload as rrs
from logutils import get_logger
from models.server_identity_key import get_private_key

logger = get_logger(__name__)

INTERNAL_ERROR = "Oops! Something went wrong. Please try again later."
REQUIRED_HEADERS = (
    "x-payload-bin",
    "x-public-key-bin",
    "x-key-id",
    "x-nonce-bin",
    "x-timestamp",
)

_request_payload: ContextVar[bytes] = ContextVar("request_payload")


def request_payload() -> bytes:
    """The decrypted payload of the request being handled."""
    return _request_payload.get()


class LoggingInterceptor(ServerInterceptor):
    server_protocol = "HTTP/2.0"

    def intercept(self, method, request_or_iterator, context, method_name):
        try:
            return method(request_or_iterator, context)
        finally:
            code = context.code()
            if code in (None, grpc.StatusCode.OK):
                logger.info("%s %s - OK -", method_name, self.server_protocol)
            else:
                logger.error(
                    "%s %s - %s -", method_name, self.server_protocol, code.name
                )


class ErrorInterceptor(ExceptionToStatusInterceptor):
    """Turn exceptions raised by handlers into gRPC status codes."""

    def handle_exception(self, ex, request_or_iterator, context, method_name):
        span = otel_trace.get_current_span()

        if isinstance(ex, NotImplementedError):
            ex = Unimplemented(str(ex))

        if isinstance(ex, GrpcException):
            span.add_event("grpc_error", {"message": ex.details})
        else:
            logger.exception("Unhandled error in %s", method_name)
            span.record_exception(ex)
            ex = Internal(INTERNAL_ERROR)

        span.set_status(otel_trace.Status(otel_trace.StatusCode.ERROR, ex.details))
        context.abort(ex.status_code, ex.details)


def _rejected(reason: str) -> Unauthenticated:
    logger.warning("Request rejected: %s", reason)
    return Unauthenticated(f"request authentication failed: {reason}")


class V1AuthInterceptor(ServerInterceptor):
    """Verify and decrypt the V1 request headers of RPCs on the given services."""

    def __init__(self, services: list[str], nonce_ttl_seconds: int):
        self._prefixes = tuple(f"/{service}/" for service in services)
        self._nonces = TTLCache(maxsize=10000, ttl=nonce_ttl_seconds)
        self._nonce_lock = threading.Lock()

    def intercept(self, method, request_or_iterator, context, method_name):
        # Health checks and other services are not signed.
        if not method_name.startswith(self._prefixes):
            return method(request_or_iterator, context)

        token = _request_payload.set(self._verify(context, method_name))
        try:
            return method(request_or_iterator, context)
        finally:
            _request_payload.reset(token)

    def _verify(self, context, method_name: str) -> bytes:
        metadata = dict(context.invocation_metadata())

        missing = [h for h in REQUIRED_HEADERS if not metadata.get(h)]
        if missing:
            raise _rejected(f"missing required headers: {', '.join(missing)}")

        try:
            key_id = int(metadata["x-key-id"])
        except ValueError:
            raise _rejected("x-key-id is not a valid integer") from None

        try:
            timestamp = int(metadata["x-timestamp"])
        except ValueError:
            raise _rejected("x-timestamp is not a valid integer") from None

        if abs(int(time.time()) - timestamp) > self._nonces.ttl:
            raise _rejected("outdated timestamp detected in request")

        nonce = metadata["x-nonce-bin"]
        with self._nonce_lock:
            if nonce in self._nonces:
                raise _rejected("nonce has already been used")
            self._nonces[nonce] = True

        try:
            with get_session() as s:
                ss_kid = get_private_key(key_id, s).private_bytes_raw()
        except ValueError as e:
            raise _rejected(str(e)) from None

        try:
            request = rrs.v1_requests_decrypt(
                ss_kid=ss_kid,
                ec_pk=metadata["x-public-key-bin"],
                nonce=nonce,
                ciphertext=metadata["x-payload-bin"],
            )
        except rrs.V1CryptographicError.FailedToDecrypt:
            raise _rejected("decryption failed") from None

        # The signed method name stops a request being replayed against another RPC.
        if request.method_name.decode() != method_name:
            raise _rejected("method name in payload does not match gRPC method")

        return request.payload
