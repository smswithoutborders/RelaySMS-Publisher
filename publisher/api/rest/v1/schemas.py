# SPDX-License-Identifier: GPL-3.0-only

import datetime
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from publisher.models.credential import MAX_USERNAME_LENGTH
from publisher.publications import PublishContentRequest


class PlatformManifest(BaseModel):
    display_name: str
    name: str
    proto_id: int = Field(..., description="0 = oauth2, 1 = pnba")
    cat_id: int = Field(..., description="0 = email, 1 = message, 2 = text, 3 = bridge")
    auth_provider: str | None = None
    supports_offline_first: bool | None = None
    icon_svg: str | None = None
    icon_png: str | None = None


class GatewayClientManifest(BaseModel):
    msisdn: str = Field(..., description="Phone number in E.164 format")
    country: str
    operator: str
    operator_code: str = Field(..., description="PLMN code (MCC + MNC)")
    protocols: list[str] = Field(..., description="How clients reach this server")


class OAuthClientMetadata(BaseModel):
    client_id: str
    dpop_bound_access_tokens: bool
    application_type: str
    redirect_uris: list[str]
    grant_types: list[str]
    response_types: list[str]
    scope: str
    token_endpoint_auth_method: str
    client_name: str
    client_uri: str


class ServerStaticPublicKey(BaseModel):
    key_id: int = Field(..., description="0-255")
    public_key: str = Field(..., description="Base64url-encoded X25519 public key")


class PublishRestContentRequest(PublishContentRequest):
    tag: str | None = Field(
        None,
        description="Shared secret for offline payloads, if the server sets one.",
    )


class PublishContentResponse(BaseModel):
    message: str | None = None
    error: str | None = None


class PublicationStat(BaseModel):
    id: int
    platform_name: str | None = None
    protocol: str | None = None
    status: str
    country_code: str | None = None
    failure_reason: str | None = None
    created_at: datetime.datetime


class PageLinks(BaseModel):
    next: str | None = Field(
        None, description="URL of the next (older) page; null on the last page."
    )
    prev: str | None = Field(
        None, description="URL of the previous (newer) page; null on the first page."
    )


class PublicationStatsPage(PageLinks):
    data: list[PublicationStat]


class StatsGroupBy(StrEnum):
    status = "status"
    platform_name = "platform_name"
    protocol = "protocol"
    country_code = "country_code"
    failure_reason = "failure_reason"


class StatsInterval(StrEnum):
    day = "day"
    week = "week"
    month = "month"
    year = "year"


class PublicationStatsSummaryGroup(BaseModel):
    """group_by column values plus their count."""

    model_config = ConfigDict(extra="allow")
    count: int


class PublicationStatsSummary(BaseModel):
    since: datetime.datetime
    until: datetime.datetime
    interval: StatsInterval | None = None
    total: int
    groups: list[PublicationStatsSummaryGroup]


class LoginRequest(BaseModel):
    username: str = Field(..., max_length=MAX_USERNAME_LENGTH)
    password: str = Field(..., max_length=256)


class CurrentCredential(BaseModel):
    username: str
    scopes: list[str]
    administrator: bool = Field(..., description="Holds every scope.")
    auth_method: Literal["session", "basic"]
    expires_at: datetime.datetime | None = Field(
        None, description="Session expiry (session auth only)."
    )


class CredentialCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    username: str = Field(..., max_length=MAX_USERNAME_LENGTH)
    scopes: list[str] = Field(..., min_length=1, max_length=32)


class CredentialUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    scopes: list[str] | None = Field(None, min_length=1, max_length=32)
    active: bool | None = None


class CredentialInfo(BaseModel):
    username: str
    active: bool
    scopes: list[str]
    administrator: bool = Field(..., description="Holds every scope.")
    created_at: datetime.datetime
    last_login_at: datetime.datetime | None = None
    active_sessions: int


class CredentialWithPassword(CredentialInfo):
    password: str = Field(..., description="Shown only in this response.")


class AuditEventInfo(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    occurred_at: datetime.datetime
    actor: str | None = Field(
        None,
        validation_alias="actor_username",
        description="Username at the time; null for the CLI or a failed login.",
    )
    action: str = Field(..., description="e.g. creds.update")
    target: str | None = Field(
        None,
        validation_alias="target_label",
        description="Target's name at the time.",
    )
    outcome: str = Field(..., description="success, denied or failed.")
    details: dict[str, Any] | None = None


class AuditEventPage(PageLinks):
    data: list[AuditEventInfo]
