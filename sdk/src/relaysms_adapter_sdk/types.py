# SPDX-License-Identifier: GPL-3.0-only
"""Requests the Publisher sends to an adapter and the results it gets back."""

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal


@dataclass(frozen=True)
class Account:
    """A user's account on the platform, with the token the Publisher stores for it."""

    identifier: str
    token: dict[str, Any] | None = None
    name: str | None = None


@dataclass(frozen=True)
class Attachment:
    data: bytes
    filename: str
    mimetype: str


@dataclass(frozen=True)
class Message:
    body: str
    recipient: str | None = None
    subject: str | None = None
    attachments: tuple[Attachment, ...] = ()


@dataclass(frozen=True)
class SendRequest:
    """Send a message from account, or as the adapter itself when account is None."""

    message: Message
    account: Account | None = None


@dataclass(frozen=True)
class SendResult:
    """The outcome of a send, with the token when the adapter refreshed it."""

    token: dict[str, Any] | None = None


@dataclass(frozen=True)
class RevokeRequest:
    account: Account


@dataclass(frozen=True)
class AuthorizationRequest:
    state: str | None = None
    code_verifier: str | None = None
    redirect_url: str | None = None
    request_identifier: str | None = None


@dataclass(frozen=True)
class AuthorizationUrl:
    url: str
    state: str | None = None
    code_verifier: str | None = None
    client_id: str | None = None
    scope: str | None = None
    redirect_url: str | None = None


@dataclass(frozen=True)
class CodeExchangeRequest:
    code: str
    code_verifier: str | None = None
    redirect_url: str | None = None
    request_identifier: str | None = None


@dataclass(frozen=True)
class CodeRequest:
    phone_number: str
    channel: str | None = None
    request_identifier: str | None = None


@dataclass(frozen=True)
class CodeSent:
    expires_at: datetime | None = None
    message: str | None = None


@dataclass(frozen=True)
class CodeVerificationRequest:
    phone_number: str
    code: str
    channel: str | None = None
    request_identifier: str | None = None


@dataclass(frozen=True)
class PasswordRequired:
    """The account has two-step verification, so verify_password comes next."""

    password_required: Literal[True] = True


@dataclass(frozen=True)
class PasswordVerificationRequest:
    phone_number: str
    password: str
    request_identifier: str | None = None
