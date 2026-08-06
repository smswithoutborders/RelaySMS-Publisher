# SPDX-License-Identifier: GPL-3.0-only

import json
from pathlib import Path as PathLib
from typing import List, Optional

from fastapi import APIRouter, HTTPException, Path, Query, Request
from fastapi.responses import HTMLResponse

from gateway_clients.gateway_client_manager import GatewayClientManager
from logutils import get_logger
from models.server_identity_key import get_public_key, get_public_keys
from platforms.adapter_manager import AdapterManager
from publications import (
    PayloadMalformedError,
    PayloadNotSupportedError,
    PublicationService,
)
from rest_services.v1.schemas import (
    GatewayClientManifest,
    OAuthClientMetadata,
    PlatformManifest,
    PublishContentRequest,
    PublishContentResponse,
    ServerStaticPublicKey,
)
from tasks.publication_task import publish_message

logger = get_logger(__name__)

router = APIRouter()

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
ALLOWED_GATEWAY_CLIENT_MANIFEST_KEYS = [
    "msisdn",
    "country",
    "operator",
    "operator_code",
    "protocols",
]


@router.get("/platforms")
def get_platforms(
    request: Request,
    name: Optional[str] = Query(
        None,
        max_length=50,
        pattern=r"^[a-zA-Z0-9_-]+$",
        description="Filter by platform name",
    ),
    proto_id: Optional[int] = Query(None, description="Filter by protocol ID"),
    cat_id: Optional[int] = Query(None, description="Filter by category ID"),
) -> List[PlatformManifest]:
    """Retrieve a list of platform adapter manifests matching optional criteria."""
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


@router.get("/gateway-clients")
def get_gateway_clients(
    request: Request,
    msisdn: Optional[str] = Query(None, description="Filter by MSISDN"),
    country: Optional[str] = Query(None, description="Filter by country"),
    operator: Optional[str] = Query(None, description="Filter by operator"),
) -> List[GatewayClientManifest]:
    """Retrieve a list of gateway clients matching optional criteria."""
    manager: GatewayClientManager = request.app.state.gateway_client_manager
    manifests = manager.list_clients(msisdn=msisdn, country=country, operator=operator)

    return [
        GatewayClientManifest(
            **{
                key: getattr(manifest, key)
                for key in ALLOWED_GATEWAY_CLIENT_MANIFEST_KEYS
            }
        )
        for manifest in manifests
    ]


@router.get("/server-keys", response_model=List[ServerStaticPublicKey])
def list_server_static_keys():
    """List all server static public keys."""
    return get_public_keys()


@router.get("/server-keys/{key_id}", response_model=ServerStaticPublicKey)
def get_server_static_key(
    key_id: int = Path(..., ge=0, le=255, description="Static key identifier"),
):
    """Return a single server static public key by key_id."""
    try:
        return get_public_key(key_id)
    except Exception as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/platforms/{platform_name}/oauth/client-metadata.json")
def get_platform_oauth_client_metadata(
    request: Request,
    platform_name: str = Path(
        ..., description="Platform name", pattern=r"^[a-zA-Z0-9_-]+$"
    ),
) -> OAuthClientMetadata:
    """Retrieve the OAuth client metadata for a platform adapter."""
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


@router.get("/platforms/{platform_name}/oauth/callback")
async def oauth_callback(
    request: Request,
    platform_name: str = Path(
        ..., description="Platform name", pattern=r"^[a-zA-Z0-9_-]+$"
    ),
) -> HTMLResponse:
    """Handle the OAuth callback from the platform."""
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
        f"<tr><td>{key}</td><td>{value}</td></tr>"
        for key, value in request.query_params.items()
    )

    return HTMLResponse(
        content=f"""
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
    )


@router.post("/publications", response_model=PublishContentResponse)
def create_publications(body: PublishContentRequest) -> PublishContentResponse:
    try:
        PublicationService.validate(body.text)
    except PayloadMalformedError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except PayloadNotSupportedError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    publish_message.delay(body.text, body.address, "https")
    logger.info("Successfully queued publication request via protocol %r.", "https")
    return PublishContentResponse(message="Publication request queued successfully.")
