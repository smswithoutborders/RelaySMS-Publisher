# SPDX-License-Identifier: GPL-3.0-only
"""Build RelaySMS Publisher platform adapters."""

from relaysms_adapter_sdk.adapter import Adapter, OAuth2Adapter, PNBAAdapter
from relaysms_adapter_sdk.errors import (
    AdapterError,
    AuthenticationError,
    InvalidParamsError,
    RateLimitedError,
    TokenInvalidError,
    UpstreamError,
)
from relaysms_adapter_sdk.paths import config_dir, state_dir
from relaysms_adapter_sdk.types import (
    Account,
    Attachment,
    AuthorizationRequest,
    AuthorizationUrl,
    CodeExchangeRequest,
    CodeRequest,
    CodeSent,
    CodeVerificationRequest,
    Message,
    PasswordRequired,
    PasswordVerificationRequest,
    RevokeRequest,
    SendRequest,
    SendResult,
)

__all__ = [
    "Account",
    "Adapter",
    "AdapterError",
    "Attachment",
    "AuthenticationError",
    "AuthorizationRequest",
    "AuthorizationUrl",
    "CodeExchangeRequest",
    "CodeRequest",
    "CodeSent",
    "CodeVerificationRequest",
    "InvalidParamsError",
    "Message",
    "OAuth2Adapter",
    "PNBAAdapter",
    "PasswordRequired",
    "PasswordVerificationRequest",
    "RateLimitedError",
    "RevokeRequest",
    "SendRequest",
    "SendResult",
    "TokenInvalidError",
    "UpstreamError",
    "config_dir",
    "state_dir",
]
