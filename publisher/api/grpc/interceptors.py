# SPDX-License-Identifier: GPL-3.0-only
"""Interceptors for the Publisher gRPC server."""

import logging
import threading
import time
from contextvars import ContextVar
from typing import override

import grpc
from cachetools import TTLCache
from grpc_interceptor import ExceptionToStatusInterceptor, ServerInterceptor
from grpc_interceptor.exceptions import (
    GrpcException,
    Internal,
    Unauthenticated,
    Unavailable,
    Unimplemented,
)
from opentelemetry import trace as otel_trace

from lib_relaysms_payload_specs.generated import relaysms_spec_payload as rrs
from publisher.db import get_session
from publisher.models.server_identity_key import get_private_key

logger = logging.getLogger(__name__)

INTERNAL_ERROR = "Oops! Something went wrong. Please try again later."
# Codes for a fault on the server, logged at ERROR. Any other code means the
# request was rejected, which is logged at WARNING.
SERVER_ERRORS = {
    grpc.StatusCode.UNKNOWN,
    grpc.StatusCode.INTERNAL,
    grpc.StatusCode.UNAVAILABLE,
    grpc.StatusCode.DATA_LOSS,
    grpc.StatusCode.DEADLINE_EXCEEDED,
}
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

    @override
    def intercept(self, method, request_or_iterator, context, method_name):
        try:
            return method(request_or_iterator, context)
        finally:
            code = context.code()  # pyright: ignore[reportAttributeAccessIssue]  (missing from grpc's stubs)
            if code in (None, grpc.StatusCode.OK):
                logger.info("%s %s - OK -", method_name, self.server_protocol)
            else:
                level = logging.ERROR if code in SERVER_ERRORS else logging.WARNING
                details = (context.details() or b"").decode(errors="replace")  # pyright: ignore[reportAttributeAccessIssue]
                logger.log(
                    level,
                    "%s %s - %s - %s",
                    method_name,
                    self.server_protocol,
                    code.name,
                    details,
                )


class ErrorInterceptor(ExceptionToStatusInterceptor):
    """Turn exceptions raised by handlers into gRPC status codes."""

    @override
    def handle_exception(self, ex, request_or_iterator, context, method_name):
        span = otel_trace.get_current_span()

        if isinstance(ex, NotImplementedError):
            ex = Unimplemented(str(ex))

        if isinstance(ex, GrpcException):
            span.add_event("grpc_error", {"message": ex.details})
        else:
            logger.error("Unhandled error in %s", method_name, exc_info=ex)
            span.record_exception(ex)
            ex = Internal(INTERNAL_ERROR)

        span.set_status(otel_trace.Status(otel_trace.StatusCode.ERROR, ex.details))
        context.abort(ex.status_code, ex.details)


def _rejected(reason: str) -> Unauthenticated:
    logger.warning("Request rejected: %s", reason)
    return Unauthenticated(f"request authentication failed: {reason}")


class V1AuthInterceptor(ServerInterceptor):
    """Verify and decrypt the V1 request headers of RPCs on the given services."""

    def __init__(
        self, services: list[str], nonce_ttl_seconds: int, nonce_cache_size: int
    ):
        self._prefixes = tuple(f"/{service}/" for service in services)
        self._ttl = nonce_ttl_seconds
        # Seen nonces don't survive a restart.
        self._started_at = int(time.time())
        # A request ahead of the server's clock stays acceptable for up to
        # twice the window after it arrives.
        self._nonces: TTLCache[bytes, bool] = TTLCache(
            maxsize=nonce_cache_size, ttl=2 * nonce_ttl_seconds, timer=time.time
        )
        self._nonce_lock = threading.Lock()

    @override
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

        if abs(time.time() - timestamp) >= self._ttl:
            raise _rejected("outdated timestamp detected in request")
        if timestamp < self._started_at:
            raise _rejected("request predates the server's start")

        nonce = metadata["x-nonce-bin"]
        try:
            with get_session() as s:
                ss_kid = get_private_key(s, key_id).private_bytes_raw()
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

        # Rejects a request replayed against another RPC.
        if request.method_name.decode() != method_name:
            raise _rejected("method name in payload does not match gRPC method")

        with self._nonce_lock:
            self._nonces.expire()
            if nonce in self._nonces:
                raise _rejected("nonce has already been used")
            # A full cache refuses new nonces instead of evicting live ones.
            if len(self._nonces) >= self._nonces.maxsize:
                raise Unavailable("Server is busy. Please try again later.")
            self._nonces[nonce] = True

        return request.payload
