# SPDX-License-Identifier: GPL-3.0-only

import html
import json
from pathlib import Path as PathLib
from typing import List, Optional

from fastapi import APIRouter, HTTPException, Path, Query, Request
from fastapi.responses import HTMLResponse

from logutils import get_logger
from platforms.adapter_manager import AdapterManager
from rest_services.v1.params import NAME_PATTERN, filter_query
from rest_services.v1.schemas import OAuthClientMetadata, PlatformManifest

logger = get_logger(__name__)

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


@router.get("", summary="List platforms")
def get_platforms(
    request: Request,
    name: Optional[str] = filter_query(50, "Filter by platform name"),
    proto_id: Optional[int] = Query(None, description="Filter by protocol ID"),
    cat_id: Optional[int] = Query(None, description="Filter by category ID"),
) -> List[PlatformManifest]:
    manager: AdapterManager = request.app.state.adapter_manager
    manifests = manager.list_adapters(name=name, proto_id=proto_id, cat_id=cat_id)

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
    "/{platform_name}/oauth/client-metadata.json", summary="OAuth client metadata"
)
def get_platform_oauth_client_metadata(
    request: Request,
    platform_name: str = Path(..., description="Platform name", pattern=NAME_PATTERN),
) -> OAuthClientMetadata:
    """Only for platforms with dynamic client registration."""
    manager: AdapterManager = request.app.state.adapter_manager
    adapters = manager.list_adapters(name=platform_name)

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
        with open(adapter_credentials, "r", encoding="utf-8") as f:
            return OAuthClientMetadata(**json.loads(f.read()))
    except FileNotFoundError as exc:
        logger.error("OAuth client metadata file not found")
        raise HTTPException(
            status_code=404, detail="OAuth client metadata file not found"
        ) from exc


@router.get("/{platform_name}/oauth/callback", summary="OAuth callback")
async def oauth_callback(
    request: Request,
    platform_name: str = Path(..., description="Platform name", pattern=NAME_PATTERN),
) -> HTMLResponse:
    """Shows the callback query parameters."""
    manager: AdapterManager = request.app.state.adapter_manager
    adapters = manager.list_adapters(name=platform_name)

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
    platform_display_name = platform_name.capitalize()

    return HTMLResponse(content=f"""
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
    """)
