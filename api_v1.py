# SPDX-License-Identifier: GPL-3.0-only

import json
from pathlib import Path as PathLib
from typing import List

from fastapi import APIRouter, HTTPException, Path, Request
from fastapi.responses import HTMLResponse

from api_schemas import OAuthClientMetadata, PlatformManifest, ServerStaticPublicKey
from logutils import get_logger
from models.server_identity_key import get_public_key, get_public_keys
from platforms.adapter_manager import AdapterManager

logger = get_logger(__name__)

router = APIRouter()

ALLOWED_PLATFORM_MANIFEST_KEYS = [
    "name",
    "shortcode",
    "protocol_type",
    "service_type",
    "icon_svg",
    "icon_png",
    "support_url_scheme",
]
ALLOWED_PLATFORMS_WITH_CLIENT_METADATA = ["bluesky"]


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


@router.get(
    "/server-keys",
    response_model=List[ServerStaticPublicKey],
)
def list_server_static_keys():
    """List all server static public keys."""
    return get_public_keys()


@router.get(
    "/server-keys/{key_id}",
    response_model=ServerStaticPublicKey,
)
def get_server_static_key(
    key_id: int = Path(..., ge=0, le=255, description="Static key identifier"),
):
    """Return a single server static public key by key_id."""
    try:
        return get_public_key(key_id)
    except Exception as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/platforms/{platform_name}")
def get_platform_data(
    platform_name: str = Path(
        ..., description="Platform name", pattern=r"^[a-zA-Z0-9_-]+$"
    ),
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
    ),
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

    if platform_name.lower() not in ALLOWED_PLATFORMS_WITH_CLIENT_METADATA:
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

    if platform_name.lower() not in ALLOWED_PLATFORMS_WITH_CLIENT_METADATA:
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
