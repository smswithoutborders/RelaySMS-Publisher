# SPDX-License-Identifier: GPL-3.0-only

import html
import json
import logging
from pathlib import Path as PathLib

from fastapi import APIRouter, Depends, HTTPException, Path, Query, Request, Response
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from publisher.api.rest.v1.errors import error_responses
from publisher.api.rest.v1.params import NAME_PATTERN, filter_query
from publisher.api.rest.v1.schemas import OAuthClientMetadata, PlatformManifest
from publisher.db import get_db
from publisher.models import platform_adapter as platform_adapters

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/platforms", tags=["Platforms"])

ALLOWED_PLATFORM_MANIFEST_KEYS = [
    "display_name",
    "name",
    "proto_id",
    "cat_id",
    "auth_provider",
    "supports_offline_first",
    "icon_svg",
    "icon_png",
]
ALLOWED_PLATFORMS_WITH_CLIENT_METADATA = ["bluesky"]
CLIENT_METADATA_404 = (
    "No enabled adapter for the platform, or the platform has no client metadata."
)


@router.get("", summary="List platforms")
def get_platforms(
    name: str | None = filter_query(50, "Filter by platform name"),
    proto_id: int | None = Query(None, description="Filter by protocol ID"),
    cat_id: int | None = Query(None, description="Filter by category ID"),
    db: Session = Depends(get_db),
) -> list[PlatformManifest]:
    """Platforms users can link: those with an installed, enabled adapter."""
    manifests = platform_adapters.find(db, name=name, proto_id=proto_id, cat_id=cat_id)

    return [
        PlatformManifest(
            **{
                key: getattr(manifest, key)
                for key in ALLOWED_PLATFORM_MANIFEST_KEYS
                if hasattr(manifest, key) and getattr(manifest, key) is not None
            }
        )
        for manifest in manifests
    ]


@router.get(
    "/{platform_name}/oauth/client-metadata.json",
    summary="OAuth client metadata",
    responses=error_responses({404: CLIENT_METADATA_404}),
)
def get_platform_oauth_client_metadata(
    platform_name: str = Path(..., description="Platform name", pattern=NAME_PATTERN),
    db: Session = Depends(get_db),
) -> OAuthClientMetadata:
    """Only for platforms with dynamic client registration, such as Bluesky."""
    adapters = platform_adapters.find(db, name=platform_name)

    if not adapters:
        raise HTTPException(status_code=404, detail="Platform not found")

    if platform_name.lower() not in ALLOWED_PLATFORMS_WITH_CLIENT_METADATA:
        raise HTTPException(
            status_code=404,
            detail="OAuth client metadata not available for this platform",
        )

    adapter_credentials = PathLib(adapters[0].path) / "credentials.json"

    if not adapter_credentials.exists():
        raise HTTPException(
            status_code=404,
            detail="OAuth client metadata file not found for this platform",
        )

    try:
        with open(adapter_credentials, encoding="utf-8") as f:
            return OAuthClientMetadata(**json.loads(f.read()))
    except FileNotFoundError as exc:
        logger.error("OAuth client metadata file not found")
        raise HTTPException(
            status_code=404, detail="OAuth client metadata file not found"
        ) from exc


@router.get(
    "/{platform_name}/oauth/callback",
    summary="OAuth callback",
    # Not HTMLResponse: that would list the JSON errors as text/html too.
    response_class=Response,
    responses={
        200: {
            "description": "The query parameters as an HTML table.",
            "content": {"text/html": {}},
        },
        **error_responses({404: CLIENT_METADATA_404}),
    },
)
async def oauth_callback(
    request: Request,
    platform_name: str = Path(..., description="Platform name", pattern=NAME_PATTERN),
    db: Session = Depends(get_db),
) -> HTMLResponse:
    """Shows the callback query parameters, as a redirect target for OAuth2 testing."""
    adapters = platform_adapters.find(db, name=platform_name)

    if not adapters:
        raise HTTPException(status_code=404, detail="Platform not found")

    if platform_name.lower() not in ALLOWED_PLATFORMS_WITH_CLIENT_METADATA:
        raise HTTPException(
            status_code=404,
            detail="OAuth client metadata not available for this platform",
        )

    table_rows = "".join(
        f"<tr><td>{html.escape(key)}</td><td>{html.escape(str(value))}</td></tr>"
        for key, value in request.query_params.items()
    )
    platform_display_name = html.escape(platform_name.capitalize())

    return HTMLResponse(
        content=f"""
    <html>
        <head><title>{platform_display_name} OAuth Callback Params</title></head>
        <body>
            <h2>{platform_display_name}'s Callback Params</h2>
            <table border="1">
                <tr><th>Parameter</th><th>Value</th></tr>
                {table_rows}
            </table>
        </body>
    </html>
    """
    )
