# SPDX-License-Identifier: GPL-3.0-only

import datetime
from enum import Enum
from typing import Generic, List, Literal, Optional, TypeVar

from pydantic import BaseModel, ConfigDict, Field

from db_types import DATE_BUCKET_UNITS
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
        description=(
            "Shared secret required to publish offline payloads "
            "over https when OFFLINE_PUBLISH_SHARED_SECRET is configured."
        ),
    )


class PublishContentResponse(BaseModel):
    message: Optional[str] = None
    error: Optional[str] = None


class PublicationStatPublic(BaseModel):
    id: int
    platform_name: Optional[str] = None
    protocol: Optional[str] = None
    status: str
    country_code: Optional[str] = None
    created_at: datetime.datetime


class PublicationStatAdmin(PublicationStatPublic):
    failure_reason: Optional[str]


StatItem = TypeVar("StatItem", PublicationStatPublic, PublicationStatAdmin)


class PublicationStatsPage(BaseModel, Generic[StatItem]):
    data: List[StatItem]
    next: Optional[str] = Field(
        None, description="URL of the next (older) page; null on the last page."
    )
    prev: Optional[str] = Field(
        None, description="URL of the previous (newer) page; null on the first page."
    )


PublicStatsPage = PublicationStatsPage[PublicationStatPublic]
AdminStatsPage = PublicationStatsPage[PublicationStatAdmin]


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
    email: str = Field(..., max_length=254)
    password: str = Field(..., max_length=256)


class AdminMe(BaseModel):
    email: str
    auth_method: Literal["session", "basic"]
    csrf_token: Optional[str] = Field(
        None,
        description="Send as X-CSRF-Token on POST requests (sessions only).",
    )
    expires_at: Optional[datetime.datetime] = Field(
        None, description="Session expiry (session auth only)."
    )
