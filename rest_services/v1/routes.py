# SPDX-License-Identifier: GPL-3.0-only

import base64
import json
import struct
from pathlib import Path as PathLib
from typing import List, Optional

from fastapi import APIRouter, HTTPException, Path, Query, Request
from fastapi.responses import HTMLResponse

from db import get_session
from lib_relaysms_payload_specs.generated import relaysms_spec_payload as rrs
from logutils import get_logger
from models.server_identity_key import get_public_key, get_public_keys
from platforms.adapter_manager import AdapterManager
from rest_services.v1.schemas import (
    OAuthClientMetadata,
    PlatformManifest,
    PublishContentRequest,
    PublishContentResponse,
    ServerStaticPublicKey,
)
from rest_services.v1.services import publish_content, store_segment_and_try_join

logger = get_logger(__name__)

router = APIRouter()

ALLOWED_PLATFORM_MANIFEST_KEYS = [
    "name",
    "shortcode",
    "proto_id",
    "cat_id",
    "icon_svg",
    "icon_png",
    "support_url_scheme",
]
ALLOWED_PLATFORMS_WITH_CLIENT_METADATA = ["bluesky"]


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


@router.post("/publications")
def create_publications(
    body: PublishContentRequest, request: Request
) -> PublishContentResponse:
    """Handle message publication requests."""
    try:
        payload_raw = base64.b64decode(body.text)
    except Exception as exc:
        logger.error("failed to decode base64 payload: %s", exc)
        raise HTTPException(
            status_code=400, detail="Invalid base64-encoded text field"
        ) from exc

    payload_type = rrs.v1_get_payload_type(payload_raw)

    match payload_type:
        case rrs.V1PayloadsTypes.WITHOUT_ATTACHMENT:
            try:
                payload = rrs.V1Payloads.deserialize_without_attachment(payload_raw)
            except Exception as exc:
                logger.exception("failed to deserialize payload: %s", exc)
                raise HTTPException(
                    status_code=400, detail="Failed to deserialize payload"
                ) from exc

            t_id = payload.get_t_id()
            if t_id is None:
                logger.error("payload is missing token ID")
                raise HTTPException(
                    status_code=400, detail="Payload is missing token ID"
                )

            with get_session() as db:
                print(">>>>>>", t_id)
                publish_content(
                    token_id=struct.pack("<I", t_id),
                    key_id=payload.get_kid(),
                    len_att=payload.get_len_att(),
                    content_ciphertext=payload.get_content(),
                    session=db,
                    adapter_manager=request.app.state.adapter_manager,
                )

        case (
            rrs.V1PayloadsTypes.WITH_ATTACHMENT_HEADER
            | rrs.V1PayloadsTypes.WITH_ATTACHMENT_NO_HEADER
        ):
            with get_session() as db:
                joined = store_segment_and_try_join(
                    sender_id=body.address,
                    payload_raw=payload_raw,
                    raw_segment=body.text.encode(),
                    db=db,
                )
                if joined is None:
                    logger.info("Segment stored. Waiting for remaining segments.")
                    return PublishContentResponse(
                        message="Segment stored. Waiting for remaining segments."
                    )
                publish_content(
                    token_id=struct.pack("<I", joined.get_t_id()),
                    key_id=joined.get_kid(),
                    len_att=joined.get_len_att(),
                    content_ciphertext=joined.get_content(),
                    session=db,
                    adapter_manager=request.app.state.adapter_manager,
                )

        case _:
            logger.error("unsupported payload type: %r", payload_type)
            raise HTTPException(
                status_code=422,
                detail=f"Payload type {payload_type!r} is not supported.",
            )

    logger.info("Content published successfully.")
    return PublishContentResponse(message="Content published successfully")
