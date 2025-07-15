"""
This program is free software: you can redistribute it under the terms
of the GNU General Public License, v. 3.0. If a copy of the GNU General
Public License was not distributed with this file, see <https://www.gnu.org/licenses/>.
"""

import datetime
from typing import Optional
from pydantic import BaseModel


class PublicationsCreate(BaseModel):
    country_code: Optional[str] = None
    platform_name: str
    source: str
    status: str
    gateway_client: Optional[str] = None
    date_created: Optional[datetime.datetime] = None


class PublicationsRead(PublicationsCreate):
    id: int


class Pagination(BaseModel):
    total_records: int
    page: int
    page_size: int
    total_pages: int


class PublicationsResponse(BaseModel):
    total_publications: int
    total_published: int
    total_failed: int
    data: list[PublicationsRead]
    pagination: Optional[Pagination] = None


class PlatformManifest(BaseModel):
    name: str
    shortcode: str
    protocol_type: str
    service_type: str
    icon_svg: Optional[str] = None
    icon_png: Optional[str] = None
    support_url_scheme: Optional[bool] = None


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
