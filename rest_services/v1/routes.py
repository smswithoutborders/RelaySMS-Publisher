# SPDX-License-Identifier: GPL-3.0-only

import html
import json
from pathlib import Path as PathLib
from typing import List, Optional

from fastapi import APIRouter, HTTPException, Path, Query, Request, Response
from fastapi.responses import HTMLResponse
from twilio.request_validator import RequestValidator
from twilio.twiml.messaging_response import MessagingResponse

from gateway_clients.gateway_client_manager import GatewayClientManager
from logutils import get_logger
from models.server_identity_key import get_public_key, get_public_keys
from platforms.adapter_manager import AdapterManager
from publications import PayloadMalformedError, PublicationService
from rest_services.v1.schemas import (
    GatewayClientManifest,
    OAuthClientMetadata,
    PlatformManifest,
    PublishContentResponse,
    PublishRestContentRequest,
    ServerStaticPublicKey,
)
from tasks.forward_task import forward_twilio_webhook
from tasks.publication_task import publish_message
from utils import get_config_bool, get_configs

logger = get_logger(__name__)

TWILIO_SMS_TRANSPORT_ENABLED = get_config_bool("TWILIO_SMS_TRANSPORT_ENABLED")
TWILIO_AUTH_TOKEN = get_configs(
    "TWILIO_AUTH_TOKEN", strict=TWILIO_SMS_TRANSPORT_ENABLED
)

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
        f"<tr><td>{html.escape(key)}</td><td>{html.escape(str(value))}</td></tr>"
        for key, value in request.query_params.items()
    )
    platform_display_name = platform_name.capitalize()

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


@router.post("/publications", response_model=PublishContentResponse)
def create_publications(body: PublishRestContentRequest) -> PublishContentResponse:
    try:
        PublicationService.validate(body.text)
    except PayloadMalformedError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    publish_message.delay(body.text, body.address, "https", body.tag)
    logger.info("Successfully queued publication request via protocol %r.", "https")
    return PublishContentResponse(message="Publication request queued successfully.")


@router.post("/twilio-sms")
async def twilio_incoming_sms(request: Request) -> Response:
    """Ingest an inbound SMS relayed by Twilio's messaging webhook."""
    if not TWILIO_SMS_TRANSPORT_ENABLED:
        raise HTTPException(status_code=404, detail="Not Found")

    form = await request.form()
    params = dict(form)
    signature = request.headers.get("X-Twilio-Signature", "")

    validator = RequestValidator(TWILIO_AUTH_TOKEN)
    if not validator.validate(str(request.url), params, signature):
        logger.warning("Rejected Twilio webhook with invalid signature.")
        raise HTTPException(status_code=403, detail="Invalid Twilio signature.")

    sender_address = params.get("From")
    text_payload = params.get("Body")

    if not sender_address or not text_payload:
        raise HTTPException(
            status_code=400, detail="Missing required field 'From' or 'Body'."
        )

    try:
        PublicationService.validate(text_payload)
    except PayloadMalformedError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    publish_message.delay(text_payload, sender_address, "sms")
    logger.info("Successfully queued publication request via protocol %r.", "sms")

    forward_twilio_webhook.delay(params, sender_address, text_payload)

    return Response(content=str(MessagingResponse()), media_type="text/xml")
