# SPDX-License-Identifier: GPL-3.0-only

import datetime
from typing import Optional

from pydantic import BaseModel, Field


class PublicationStatsCreate(BaseModel):
    country_code: Optional[str] = None
    platform_name: Optional[str] = None
    protocol: Optional[str] = None
    status: str
    failure_reason: Optional[str] = None
    created_at: Optional[datetime.datetime] = None


class PublicationStatsRead(PublicationStatsCreate):
    id: int


class Pagination(BaseModel):
    total_records: int
    page: int
    page_size: int
    total_pages: int


class PublicationStatsResponse(BaseModel):
    total_publications: int
    total_published: int
    total_failed: int
    data: list[PublicationStatsRead]
    pagination: Optional[Pagination] = None


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


class PublishContentResponse(BaseModel):
    message: Optional[str] = None
    error: Optional[str] = None
