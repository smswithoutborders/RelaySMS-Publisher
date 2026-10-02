# SPDX-License-Identifier: GPL-3.0-only

import datetime
from enum import Enum
from typing import List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

from db_types import DATE_BUCKET_UNITS
from models.credential import MAX_USERNAME_LENGTH
from models.publication_stats import GROUPABLE_COLUMNS


class PlatformManifest(BaseModel):
    display_name: str
    name: str
    proto_id: int
    cat_id: int
    auth_provider: Optional[str] = None
    supports_offline_first: Optional[bool] = None
    icon_svg: Optional[str] = None
    icon_png: Optional[str] = None


class GatewayClientManifest(BaseModel):
    msisdn: str
    country: str
    operator: str
    operator_code: str
    protocols: list[str]


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
    key_id: int
    public_key: str


class PublishContentRequest(BaseModel):
    address: str = Field(
        ...,
        description="Sender phone number in E.164 format",
        examples=["+12025550123"],
    )
    text: str = Field(
        ...,
        description="Base64-encoded SMS payload",
    )


class PublishRestContentRequest(PublishContentRequest):
    tag: Optional[str] = Field(
        None,
        description="Shared secret for offline payloads, if the server sets one.",
    )


class PublishContentResponse(BaseModel):
    message: Optional[str] = None
    error: Optional[str] = None


class PublicationStat(BaseModel):
    id: int
    platform_name: Optional[str] = None
    protocol: Optional[str] = None
    status: str
    country_code: Optional[str] = None
    failure_reason: Optional[str] = None
    created_at: datetime.datetime


class PublicationStatsPage(BaseModel):
    data: List[PublicationStat]
    next: Optional[str] = Field(
        None, description="URL of the next (older) page; null on the last page."
    )
    prev: Optional[str] = Field(
        None, description="URL of the previous (newer) page; null on the first page."
    )


StatsGroupBy = Enum(
    "StatsGroupBy", {name: name for name in GROUPABLE_COLUMNS}, type=str
)
StatsInterval = Enum(
    "StatsInterval", {unit: unit for unit in DATE_BUCKET_UNITS}, type=str
)


class PublicationStatsSummaryGroup(BaseModel):
    """group_by column values plus their count."""

    model_config = ConfigDict(extra="allow")
    count: int


class PublicationStatsSummary(BaseModel):
    since: datetime.datetime
    until: datetime.datetime
    interval: Optional[StatsInterval] = None
    total: int
    groups: List[PublicationStatsSummaryGroup]


class LoginRequest(BaseModel):
    username: str = Field(..., max_length=MAX_USERNAME_LENGTH)
    password: str = Field(..., max_length=256)


class CurrentCredential(BaseModel):
    username: str
    scopes: List[str]
    administrator: bool = Field(..., description="Holds every scope.")
    auth_method: Literal["session", "basic"]
    expires_at: Optional[datetime.datetime] = Field(
        None, description="Session expiry (session auth only)."
    )


class CredentialCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    username: str = Field(..., max_length=MAX_USERNAME_LENGTH)
    scopes: List[str] = Field(..., min_length=1, max_length=32)


class CredentialUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    scopes: Optional[List[str]] = Field(None, min_length=1, max_length=32)
    active: Optional[bool] = None


class CredentialInfo(BaseModel):
    username: str
    active: bool
    scopes: List[str]
    administrator: bool = Field(..., description="Holds every scope.")
    created_at: datetime.datetime
    last_login_at: Optional[datetime.datetime] = None
    active_sessions: int


class CredentialWithPassword(CredentialInfo):
    password: str = Field(..., description="Shown only in this response.")
