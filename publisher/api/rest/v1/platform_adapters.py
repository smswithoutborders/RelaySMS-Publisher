# SPDX-License-Identifier: GPL-3.0-only
"""Managing installed platform adapters."""

from contextlib import contextmanager

from fastapi import APIRouter, Depends, Path, Request, Response, Security
from sqlalchemy.orm import Session

from publisher.api.rest.v1.auth import AuthContext, authorize
from publisher.api.rest.v1.errors import ApiError
from publisher.api.rest.v1.params import check_if_match, etag
from publisher.api.rest.v1.schemas import PlatformAdapterInfo, PlatformAdapterUpdate
from publisher.db import get_db
from publisher.models import credential as credentials
from publisher.models import platform_adapter as platform_adapters
from publisher.models.credential import Scope
from publisher.models.platform_adapter import PlatformAdapter
from publisher.platforms import manager
from publisher.platforms.manager import (
    AdapterConflictError,
    AdapterError,
    AdapterInUseError,
)

router = APIRouter(prefix="/platforms/adapters", tags=["Platform Adapters"])

ADAPTER_ID_PATH = Path(..., max_length=36, pattern=r"^[A-Za-z0-9._-]+$")


def _etag(adapter: PlatformAdapter) -> str:
    return etag(adapter.id, adapter.version)


def _load(db: Session, adapter_id: str) -> PlatformAdapter:
    adapter = db.get(PlatformAdapter, adapter_id)
    if adapter is None:
        raise ApiError(404, "Adapter not found.")
    return adapter


def _info(adapter: PlatformAdapter, names: dict) -> PlatformAdapterInfo:
    return PlatformAdapterInfo(
        id=adapter.id,
        name=adapter.name,
        display_name=adapter.display_name,
        proto_id=adapter.proto_id,
        cat_id=adapter.cat_id,
        auth_provider=adapter.auth_provider,
        supports_offline_first=adapter.supports_offline_first,
        icon_svg=adapter.icon_svg,
        icon_png=adapter.icon_png,
        source_url=adapter.source_url,
        commit=adapter.commit,
        enabled=adapter.is_enabled,
        created_at=adapter.created_at,
        created_by=names.get(adapter.created_by),
        updated_at=adapter.updated_at,
        updated_by=names.get(adapter.updated_by),
    )


def _respond(
    db: Session, response: Response, adapter: PlatformAdapter
) -> PlatformAdapterInfo:
    response.headers["ETag"] = _etag(adapter)
    names = credentials.usernames(db, [adapter.created_by, adapter.updated_by])
    return _info(adapter, names)


@contextmanager
def _adapter_errors(context: AuthContext):
    by = f"actor {context.credential.id}"
    try:
        yield
    except (AdapterInUseError, AdapterConflictError) as e:
        raise ApiError(409, str(e), log=f"{by}: {e}") from None
    except AdapterError as e:
        raise ApiError(400, str(e), log=f"{by}: {e}") from None


@router.get("", response_model=list[PlatformAdapterInfo], summary="List adapters")
def list_adapters(
    context: AuthContext = Security(authorize, scopes=[Scope.PLATFORMS_READ]),
    db: Session = Depends(get_db),
) -> list[PlatformAdapterInfo]:
    """Every installed adapter, disabled ones included. Scope: platforms:read."""
    adapters = platform_adapters.find(db, include_disabled=True)
    names = credentials.usernames(
        db, [i for a in adapters for i in (a.created_by, a.updated_by)]
    )
    return [_info(adapter, names) for adapter in adapters]


@router.get("/{adapter_id}", response_model=PlatformAdapterInfo, summary="Get adapter")
def get_adapter(
    response: Response,
    adapter_id: str = ADAPTER_ID_PATH,
    context: AuthContext = Security(authorize, scopes=[Scope.PLATFORMS_READ]),
    db: Session = Depends(get_db),
) -> PlatformAdapterInfo:
    """Returns the ETag to send as If-Match. Scope: platforms:read."""
    return _respond(db, response, _load(db, adapter_id))


@router.patch(
    "/{adapter_id}", response_model=PlatformAdapterInfo, summary="Enable or disable"
)
def update_adapter(
    body: PlatformAdapterUpdate,
    request: Request,
    response: Response,
    adapter_id: str = ADAPTER_ID_PATH,
    context: AuthContext = Security(authorize, scopes=[Scope.PLATFORMS_WRITE]),
    db: Session = Depends(get_db),
) -> PlatformAdapterInfo:
    """Needs If-Match. Scope: platforms:write.

    A disabled adapter is hidden from users but still revokes tokens.
    """
    adapter = _load(db, adapter_id)
    check_if_match(request, _etag(adapter), "adapter")
    with _adapter_errors(context):
        manager.set_enabled(db, adapter, body.enabled, actor=context.credential)
    db.commit()
    return _respond(db, response, adapter)


@router.delete("/{adapter_id}", status_code=204, summary="Uninstall adapter")
def delete_adapter(
    request: Request,
    adapter_id: str = ADAPTER_ID_PATH,
    context: AuthContext = Security(authorize, scopes=[Scope.PLATFORMS_WRITE]),
    db: Session = Depends(get_db),
) -> Response:
    """Needs If-Match. Scope: platforms:write.

    Refused with 409 while accounts are linked through it; disable it instead.
    """
    adapter = _load(db, adapter_id)
    check_if_match(request, _etag(adapter), "adapter")
    with _adapter_errors(context):
        manager.remove(db, adapter, actor=context.credential)
    db.commit()
    return Response(status_code=204)
