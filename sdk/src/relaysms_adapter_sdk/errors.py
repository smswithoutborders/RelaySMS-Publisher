# SPDX-License-Identifier: GPL-3.0-only
"""Errors an adapter raises, each sent to the Publisher with its own code."""

from typing import Any

# JSON-RPC 2.0 reserved codes.
PARSE_ERROR = -32700
INVALID_REQUEST = -32600
METHOD_NOT_FOUND = -32601
INVALID_PARAMS = -32602
INTERNAL_ERROR = -32603


class AdapterError(Exception):
    """A failure the Publisher should report as is."""

    code: int = -32000

    def __init__(self, message: str, *, code: int | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.data: dict[str, Any] | None = None
        if code is not None:
            self.code = code


class InvalidParamsError(AdapterError):
    """The request is missing a field or has a bad value."""

    code = INVALID_PARAMS


class AuthenticationError(AdapterError):
    """The code, password or authorization the user gave was rejected."""

    code = -32001


class TokenInvalidError(AdapterError):
    """The stored token no longer works, so the user has to link the account again."""

    code = -32002


class RateLimitedError(AdapterError):
    """The platform is throttling requests."""

    code = -32003

    def __init__(self, message: str, *, retry_after: int | None = None) -> None:
        super().__init__(message)
        if retry_after is not None:
            self.data = {"retry_after": retry_after}

    @property
    def retry_after(self) -> int | None:
        return (self.data or {}).get("retry_after")


class UpstreamError(AdapterError):
    """The platform failed or couldn't be reached."""

    code = -32004


_BY_CODE: dict[int, type[AdapterError]] = {
    cls.code: cls
    for cls in (
        InvalidParamsError,
        AuthenticationError,
        TokenInvalidError,
        RateLimitedError,
        UpstreamError,
    )
}


def from_code(code: int, message: str, data: Any = None) -> AdapterError:
    """Rebuild the error an adapter raised from its code."""
    cls = _BY_CODE.get(code)
    error = cls(message) if cls else AdapterError(message, code=code)
    error.data = data if isinstance(data, dict) else None
    return error
