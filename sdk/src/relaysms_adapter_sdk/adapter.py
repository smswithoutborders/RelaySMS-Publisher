# SPDX-License-Identifier: GPL-3.0-only
"""The base classes adapters subclass, one per authentication protocol.

Any method may be async. Failures are raised as AdapterError subclasses.
"""

from abc import ABC, abstractmethod
from collections.abc import Awaitable, Mapping
from typing import ClassVar

from relaysms_adapter_sdk.errors import METHOD_NOT_FOUND, AdapterError
from relaysms_adapter_sdk.types import (
    Account,
    AuthorizationRequest,
    AuthorizationUrl,
    CodeExchangeRequest,
    CodeRequest,
    CodeSent,
    CodeVerificationRequest,
    PasswordRequired,
    PasswordVerificationRequest,
    RevokeRequest,
    SendRequest,
    SendResult,
)

type MaybeAwaitable[T] = T | Awaitable[T]


class Adapter(ABC):
    # The methods the Publisher may call, with the request type each takes.
    RPC_METHODS: ClassVar[Mapping[str, type]] = {
        "send_message": SendRequest,
        "revoke": RevokeRequest,
    }

    @abstractmethod
    def send_message(self, request: SendRequest) -> MaybeAwaitable[SendResult]:
        """Send a message, returning the token when it was refreshed."""

    @abstractmethod
    def revoke(self, request: RevokeRequest) -> MaybeAwaitable[None]:
        """End the account's access, when the user unlinks it."""


class OAuth2Adapter(Adapter):
    RPC_METHODS: ClassVar[Mapping[str, type]] = {
        **Adapter.RPC_METHODS,
        "create_authorization_url": AuthorizationRequest,
        "exchange_code": CodeExchangeRequest,
    }

    @abstractmethod
    def create_authorization_url(
        self, request: AuthorizationRequest
    ) -> MaybeAwaitable[AuthorizationUrl]:
        """Return the URL the user opens to grant access."""

    @abstractmethod
    def exchange_code(self, request: CodeExchangeRequest) -> MaybeAwaitable[Account]:
        """Exchange the authorization code for the account and its token."""


class PNBAAdapter(Adapter):
    RPC_METHODS: ClassVar[Mapping[str, type]] = {
        **Adapter.RPC_METHODS,
        "send_code": CodeRequest,
        "verify_code": CodeVerificationRequest,
        "verify_password": PasswordVerificationRequest,
    }

    @abstractmethod
    def send_code(self, request: CodeRequest) -> MaybeAwaitable[CodeSent]:
        """Send a one-time code to the phone number."""

    @abstractmethod
    def verify_code(
        self, request: CodeVerificationRequest
    ) -> MaybeAwaitable[Account | PasswordRequired]:
        """Check the code, returning PasswordRequired for two-step accounts."""

    def verify_password(
        self, request: PasswordVerificationRequest
    ) -> MaybeAwaitable[Account]:
        """Check the two-step verification password."""
        raise AdapterError(
            f"{type(self).__name__} has no two-step passwords.", code=METHOD_NOT_FOUND
        )
