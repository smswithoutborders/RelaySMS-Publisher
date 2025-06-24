"""
This program is free software: you can redistribute it under the terms
of the GNU General Public License, v. 3.0. If a copy of the GNU General
Public License was not distributed with this file, see <https://www.gnu.org/licenses/>.
"""

import datetime
import json
from pathlib import Path as PathLib
from typing import Optional, List
from fastapi import APIRouter, HTTPException, Query, Path, Request
from fastapi.responses import HTMLResponse
from api_schemas import (
    PublicationsRead,
    PublicationsResponse,
    Pagination,
    PlatformManifest,
    OAuthClientMetadata,
)
from publications import fetch_publication
from platforms.adapter_manager import AdapterManager
from logutils import get_logger

logger = get_logger(__name__)

router = APIRouter()

ALLOWED_PLATFORM_MANIFEST_KEYS = [
    "name",
    "shortcode",
    "protocol",
    "service_type",
    "icon_svg",
    "icon_png",
    "support_url_scheme",
]
ALLOWED_PLATFORMS_WITH_CLIENT_METADATA = ["bluesky"]


@router.get("/metrics/publications", response_model=PublicationsResponse)
def get_publication(
    start_date: datetime.date = Query(...),
    end_date: datetime.date = Query(...),
    country_code: Optional[str] = Query(None),
    platform_name: Optional[str] = Query(None),
    source: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    gateway_client: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(10, ge=1, le=100),
):
    """Retrieve metrics with optional filters."""
    logger.debug(
        "Fetching metrics with filters: start_date=%s, end_date=%s, "
        "country_code=%s, platform_name=%s, source=%s, status=%s, "
        "gateway_client=%s, page=%s, page_size=%s",
        start_date,
        end_date,
        country_code,
        platform_name,
        source,
        status,
        gateway_client,
        page,
        page_size,
    )

    filters = {
        "country_code": country_code,
        "platform_name": platform_name,
        "source": source,
        "status": status,
        "gateway_client": gateway_client,
    }

    try:
        result = fetch_publication(start_date, end_date, filters, page, page_size)
        publications = [
            PublicationsRead(**publication.__data__) for publication in result["data"]
        ]
        total_records = result.get("total_publications", 0)
        total_pages = (total_records + page_size - 1) // page_size
        return PublicationsResponse(
            total_publications=result.get("total_publications", 0),
            total_published=result.get("total_published", 0),
            total_failed=result.get("total_failed", 0),
            data=publications,
            pagination=Pagination(
                total_records=total_records,
                page=page,
                page_size=page_size,
                total_pages=total_pages,
            ),
        )

    except Exception as e:
        logger.error(f"Error fetching publications: {e}")
        raise HTTPException(status_code=500, detail="Error fetching publications")


@router.get("/platforms")
def get_platforms() -> List[PlatformManifest]:
    """
    Retrieve a list of platform adapter manifests.
    """
    AdapterManager._populate_registry()
    platforms = []
    for manifest in AdapterManager._registry.values():
        manifest_copy = {
            key: value
            for key, value in manifest.items()
            if key in ALLOWED_PLATFORM_MANIFEST_KEYS
        }
        platforms.append(manifest_copy)
    return platforms


@router.get("/platforms/{platform_name}")
def get_platform_data(
    platform_name: str = Path(
        ..., description="Platform name", pattern=r"^[a-zA-Z0-9_-]+$"
    )
) -> PlatformManifest:
    """Retrieve the manifest of a platform adapter."""
    AdapterManager._populate_registry()
    adapter = next(
        (
            manifest
            for manifest in AdapterManager._registry.values()
            if manifest["name"].lower() == platform_name.lower()
        ),
        None,
    )
    if not adapter:
        raise HTTPException(status_code=404, detail="Platform not found")

    adapter_copy = {
        key: value
        for key, value in adapter.items()
        if key in ALLOWED_PLATFORM_MANIFEST_KEYS
    }
    return adapter_copy


@router.get("/platforms/{platform_name}/oauth/client-metadata.json")
def get_platform_oauth_client_metadata(
    platform_name: str = Path(
        ..., description="Platform name", pattern=r"^[a-zA-Z0-9_-]+$"
    )
) -> OAuthClientMetadata:
    """Retrieve the OAuth client metadata for a platform adapter."""
    AdapterManager._populate_registry()
    adapter = next(
        (
            manifest
            for manifest in AdapterManager._registry.values()
            if manifest["name"].lower() == platform_name.lower()
        ),
        None,
    )
    if not adapter:
        raise HTTPException(status_code=404, detail="Platform not found")

    if not platform_name.lower() in ALLOWED_PLATFORMS_WITH_CLIENT_METADATA:
        raise HTTPException(
            status_code=404,
            detail="OAuth client metadata not available for this platform",
        )

    adapter_credentials = PathLib(adapter.get("path")) / "credentials.json"

    if not adapter_credentials.exists():
        raise HTTPException(
            status_code=404,
            detail="OAuth client metadata file not found for this platform",
        )

    try:
        with open(adapter_credentials, "r", encoding="utf-8") as file:
            creds = file.read()
            client_metadata = OAuthClientMetadata(**json.loads(creds))
        return client_metadata
    except FileNotFoundError as exc:
        logger.error("OAuth client metadata file not found")
        raise HTTPException(
            status_code=404, detail="OAuth client metadata file not found"
        ) from exc


@router.get("/platforms/{platform_name}/oauth/callback")
async def oauth_callback(
    request: Request,
    platform_name: str = Path(
        ..., description="Platform name", pattern=r"^[a-zA-Z0-9_-]+$"
    ),
) -> HTMLResponse:
    """
    Handle the OAuth callback from the platform.
    """
    AdapterManager._populate_registry()
    adapter = next(
        (
            manifest
            for manifest in AdapterManager._registry.values()
            if manifest["name"].lower() == platform_name.lower()
        ),
        None,
    )
    if not adapter:
        raise HTTPException(status_code=404, detail="Platform not found")

    if not platform_name.lower() in ALLOWED_PLATFORMS_WITH_CLIENT_METADATA:
        raise HTTPException(
            status_code=404,
            detail="OAuth client metadata not available for this platform",
        )

    table_rows = ""
    for key, value in request.query_params.items():
        table_rows += f"<tr><td>{key}</td><td>{value}</td></tr>"

    html_content = f"""
    <html>
        <head><title>{platform_name.capitalize()} OAuth Callback Params</title></head>
        <body>
            <h2>{platform_name.capitalize()}'s Callback Params</h2>
            <table border="1">
                <tr><th>Parameter</th><th>Value</th></tr>
                {table_rows}
            </table>
        </body>
    </html>
    """
    return HTMLResponse(content=html_content)
