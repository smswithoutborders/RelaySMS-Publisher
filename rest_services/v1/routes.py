# SPDX-License-Identifier: GPL-3.0-only

import dataclasses
import datetime
import html
import json
from pathlib import Path as PathLib
from typing import List, Optional, Union

from fastapi import APIRouter, Depends, HTTPException, Path, Query, Request, Response
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session
from twilio.request_validator import RequestValidator
from twilio.twiml.messaging_response import MessagingResponse

import admin_auth_config
from db import get_db
from db_types import as_utc, utc_now
from gateway_clients.gateway_client_manager import GatewayClientManager
from logutils import get_logger
from models import admin_session as admin_sessions
from models import publication_stats
from models.admin_session import AdminSession
from models.admin_user import AdminUser, record_login, verify_credentials
from models.server_identity_key import get_public_key, get_public_keys
from platforms.adapter_manager import AdapterManager
from publications import PayloadMalformedError, PublicationService
from rest_services.v1.auth import (
    AdminContext,
    check_origin,
    clear_session_cookie,
    optional_admin,
    require_admin,
    set_session_cookie,
)
from rest_services.v1.schemas import (
    AdminMe,
    AdminStatsPage,
    GatewayClientManifest,
    LoginRequest,
    OAuthClientMetadata,
    PlatformManifest,
    PublicationStatsSummary,
    PublicStatsPage,
    PublishContentResponse,
    PublishRestContentRequest,
    ServerStaticPublicKey,
    StatsGroupBy,
    StatsInterval,
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


NAME_PATTERN = r"^[a-zA-Z0-9_-]+$"
STATS_SUMMARY_DEFAULT_WINDOW = datetime.timedelta(days=30)
PUBLIC_STATS_CACHE_CONTROL = "public, max-age=60"
PRIVATE_CACHE_CONTROL = "private, no-store"


def _filter_query(max_length: int, description: str):
    return Query(
        None,
        max_length=max_length,
        pattern=NAME_PATTERN,
        description=description,
    )


def stats_filters(
    status: Optional[str] = _filter_query(20, "Filter by status"),
    platform_name: Optional[str] = _filter_query(100, "Filter by platform name"),
    protocol: Optional[str] = _filter_query(20, "Filter by ingestion protocol"),
    country_code: Optional[str] = _filter_query(10, "Filter by ISO country code"),
    since: Optional[datetime.datetime] = Query(
        None,
        description="Created at or after (ISO-8601, UTC if no offset)",
    ),
    until: Optional[datetime.datetime] = Query(
        None,
        description="Created before (ISO-8601, UTC if no offset)",
    ),
) -> publication_stats.StatsFilters:
    since, until = as_utc(since), as_utc(until)
    if since is not None and until is not None and since >= until:
        raise HTTPException(status_code=400, detail="'since' must be before 'until'.")

    return publication_stats.StatsFilters(
        status=status,
        platform_name=platform_name,
        protocol=protocol,
        country_code=country_code,
        since=since,
        until=until,
    )


def _stats_response(content: BaseModel, context: Optional[AdminContext]) -> Response:
    return Response(
        content=content.model_dump_json(),
        media_type="application/json",
        headers={
            "Cache-Control": (
                PUBLIC_STATS_CACHE_CONTROL if context is None else PRIVATE_CACHE_CONTROL
            ),
            "Vary": "Authorization, Cookie",
        },
    )


def _page_link(request: Request, cursor: Optional[str]) -> Optional[str]:
    return str(request.url.include_query_params(cursor=cursor)) if cursor else None


def _admin_me(
    admin: AdminUser,
    session: Optional[AdminSession] = None,
    session_token: Optional[str] = None,
) -> AdminMe:
    if session is None:
        return AdminMe(email=admin.email, auth_method="basic")
    return AdminMe(
        email=admin.email,
        auth_method="session",
        csrf_token=admin_sessions.csrf_token_for(session_token),
        expires_at=session.expires_at,
    )


@router.get("/platforms")
def get_platforms(
    request: Request,
    name: Optional[str] = _filter_query(50, "Filter by platform name"),
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
    platform_name: str = Path(..., description="Platform name", pattern=NAME_PATTERN),
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
    platform_name: str = Path(..., description="Platform name", pattern=NAME_PATTERN),
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


@router.get(
    "/stats/publications",
    response_model=None,
    responses={200: {"model": Union[PublicStatsPage, AdminStatsPage]}},
)
def list_publication_stats(
    request: Request,
    filters: publication_stats.StatsFilters = Depends(stats_filters),
    limit: int = Query(50, ge=1, le=200, description="Page size"),
    cursor: Optional[str] = Query(
        None, max_length=512, description="Set by the next and prev links"
    ),
    context: Optional[AdminContext] = Depends(optional_admin),
    db: Session = Depends(get_db),
) -> Response:
    """List publish attempts."""
    decoded_cursor = publication_stats.decode_cursor(cursor) if cursor else None

    is_admin = context is not None
    page = publication_stats.list_stats(
        db,
        filters=filters,
        limit=limit,
        cursor=decoded_cursor,
        is_admin=is_admin,
    )
    page_model = AdminStatsPage if is_admin else PublicStatsPage
    return _stats_response(
        page_model.model_validate(
            {
                "data": page.data,
                "next": _page_link(request, page.next_cursor),
                "prev": _page_link(request, page.prev_cursor),
            }
        ),
        context,
    )


@router.get(
    "/stats/publications/summary",
    response_model=None,
    responses={200: {"model": PublicationStatsSummary}},
)
def summarize_publication_stats(
    filters: publication_stats.StatsFilters = Depends(stats_filters),
    group_by: List[StatsGroupBy] = Query(
        [StatsGroupBy.status],
        description="Repeatable. failure_reason requires auth.",
    ),
    interval: Optional[StatsInterval] = Query(
        None, description="Also group by period start, in UTC. Weeks start Monday."
    ),
    context: Optional[AdminContext] = Depends(optional_admin),
    db: Session = Depends(get_db),
) -> Response:
    """Count publish attempts per group. Defaults to the last 30 days."""
    columns = list(dict.fromkeys(item.value for item in group_by))
    unit = interval.value if interval else None
    until = filters.until or utc_now()
    since = filters.since or until - STATS_SUMMARY_DEFAULT_WINDOW
    if since >= until:
        raise HTTPException(status_code=400, detail="'since' must be before 'until'.")

    try:
        groups = publication_stats.summarize(
            db,
            group_by=columns,
            filters=dataclasses.replace(filters, since=since, until=until),
            interval=unit,
            is_admin=context is not None,
        )
    except publication_stats.AdminOnlyColumnError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    return _stats_response(
        PublicationStatsSummary(
            since=since,
            until=until,
            interval=unit,
            total=sum(group["count"] for group in groups),
            groups=groups,
        ),
        context,
    )


@router.post("/auth/login", response_model=AdminMe)
def admin_login(
    body: LoginRequest,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
) -> AdminMe:
    """Start a web session (HttpOnly cookie)."""
    check_origin(request)

    admin = verify_credentials(db, body.email, body.password)
    if admin is None:
        raise HTTPException(status_code=401, detail="Invalid email or password.")

    admin_session, raw_token = admin_sessions.create(
        db,
        admin,
        max_age=admin_auth_config.settings.max_age,
        user_agent=request.headers.get("User-Agent"),
    )
    record_login(admin)
    db.commit()

    set_session_cookie(response, raw_token)
    response.headers["Cache-Control"] = PRIVATE_CACHE_CONTROL
    logger.info("Admin %s logged in.", admin.id)
    return _admin_me(admin, admin_session, raw_token)


@router.post("/auth/logout", status_code=204)
def admin_logout(
    context: AdminContext = Depends(require_admin),
    db: Session = Depends(get_db),
) -> Response:
    """End the current web session."""
    if context.session is None:
        raise HTTPException(
            status_code=400,
            detail="Logout applies to session (cookie) authentication only.",
        )

    db.delete(context.session)
    db.commit()

    response = Response(status_code=204)
    clear_session_cookie(response)
    return response


@router.get("/auth/me", response_model=AdminMe)
def admin_me(
    response: Response, context: AdminContext = Depends(require_admin)
) -> AdminMe:
    """Return the current admin and, for sessions, the CSRF token."""
    response.headers["Cache-Control"] = PRIVATE_CACHE_CONTROL
    return _admin_me(context.admin, context.session, context.session_token)
