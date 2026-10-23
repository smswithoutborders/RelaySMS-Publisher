# SPDX-License-Identifier: GPL-3.0-only
"""Managing installed platform adapters."""

import uuid
from contextlib import contextmanager
from dataclasses import asdict

from fastapi import APIRouter, Depends, Path, Request, Response, Security
from sqlalchemy.orm import Session

from publisher.api.rest.v1.auth import AuthContext, authorize
from publisher.api.rest.v1.errors import (
    CONCURRENT_CHANGE,
    IF_MATCH_ERRORS,
    ApiError,
    error_responses,
)
from publisher.api.rest.v1.params import check_if_match, etag
from publisher.api.rest.v1.schemas import (
    AdapterConfig,
    AdapterConfigUpdate,
    AdapterField,
    AdapterInstall,
    AdapterJobInfo,
    AdapterSetting,
    AdapterSetup,
    AdapterUpgrade,
    PlatformAdapterInfo,
    PlatformAdapterUpdate,
)
from publisher.db import get_db
from publisher.models import credential as credentials
from publisher.models import platform_adapter as platform_adapters
from publisher.models import platform_adapter_job as jobs
from publisher.models.credential import Scope
from publisher.models.platform_adapter import PlatformAdapter
from publisher.platforms import adapter_config, manager
from publisher.platforms.manager import (
    AdapterConflictError,
    AdapterError,
    AdapterFaultError,
    AdapterInUseError,
)
from publisher.tasks.platform_task import run_adapter_job

router = APIRouter(
    prefix="/platforms/adapters",
    tags=["Platform Adapters"],
)

ADAPTER_ID_PATH = Path(..., max_length=36, pattern=r"^[A-Za-z0-9._-]+$")
NOT_FOUND = {404: "No adapter with that ID."}
NOT_ADMINISTRATOR = {403: "Also when the credential isn't an administrator."}
QUEUE_DOWN = {503: "The job queue is unavailable. Try again later."}
ADAPTER_BROKEN = {502: "The adapter, or its files on this server, are broken."}


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
        tag=adapter.tag,
        commit=adapter.commit,
        enabled=adapter.is_enabled,
        configured=adapter_config.is_configured(adapter),
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
    except AdapterFaultError as e:
        message = "The adapter or its files are broken; see the server log."
        raise ApiError(502, message, log=f"{by}: {e}") from None
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


@router.get(
    "/{adapter_id}",
    response_model=PlatformAdapterInfo,
    summary="Get adapter",
    responses=error_responses(NOT_FOUND),
)
def get_adapter(
    response: Response,
    adapter_id: str = ADAPTER_ID_PATH,
    context: AuthContext = Security(authorize, scopes=[Scope.PLATFORMS_READ]),
    db: Session = Depends(get_db),
) -> PlatformAdapterInfo:
    """Returns the ETag to send as If-Match. Scope: platforms:read."""
    return _respond(db, response, _load(db, adapter_id))


@router.patch(
    "/{adapter_id}",
    response_model=PlatformAdapterInfo,
    summary="Enable or disable",
    responses=error_responses(NOT_FOUND, CONCURRENT_CHANGE, IF_MATCH_ERRORS),
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


@router.delete(
    "/{adapter_id}",
    status_code=204,
    summary="Uninstall adapter",
    responses=error_responses(
        NOT_FOUND,
        IF_MATCH_ERRORS,
        {409: "Accounts are linked through it, or it changed at the same moment."},
    ),
)
def delete_adapter(
    request: Request,
    adapter_id: str = ADAPTER_ID_PATH,
    context: AuthContext = Security(authorize, scopes=[Scope.PLATFORMS_WRITE]),
    db: Session = Depends(get_db),
) -> Response:
    """Needs If-Match. Scope: platforms:write.

    Refused while accounts are linked through it; disable it instead.
    """
    adapter = _load(db, adapter_id)
    check_if_match(request, _etag(adapter), "adapter")
    with _adapter_errors(context):
        manager.remove(db, adapter, actor=context.credential)
    db.commit()
    manager.delete_files(adapter)
    return Response(status_code=204)


def _require_administrator(context: AuthContext, what: str) -> None:
    if not context.credential.is_administrator:
        raise ApiError(403, f"{what} needs an administrator.")


def _config(adapter: PlatformAdapter) -> AdapterConfig:
    declared = adapter_config.load_manifest(adapter)
    return AdapterConfig(
        settings=[
            AdapterSetting(**asdict(s.field), value=s.value, is_set=s.is_set)
            for s in adapter_config.show(adapter, declared)
        ],
        setup=[AdapterField(**asdict(field)) for field in declared.setup],
    )


@router.get(
    "/{adapter_id}/config",
    response_model=AdapterConfig,
    summary="Get settings",
    responses=error_responses(NOT_ADMINISTRATOR, NOT_FOUND, ADAPTER_BROKEN),
)
def get_config(
    response: Response,
    adapter_id: str = ADAPTER_ID_PATH,
    context: AuthContext = Security(authorize, scopes=[Scope.PLATFORMS_WRITE]),
    db: Session = Depends(get_db),
) -> AdapterConfig:
    """Returns the ETag to send as If-Match. Administrators only."""
    _require_administrator(context, "Adapter settings")
    adapter = _load(db, adapter_id)
    response.headers["ETag"] = _etag(adapter)
    with _adapter_errors(context):
        return _config(adapter)


@router.patch(
    "/{adapter_id}/config",
    response_model=AdapterConfig,
    summary="Change settings",
    responses=error_responses(
        NOT_ADMINISTRATOR,
        NOT_FOUND,
        CONCURRENT_CHANGE,
        IF_MATCH_ERRORS,
        ADAPTER_BROKEN,
        {400: "A key isn't a setting of the adapter, or a value has the wrong type."},
    ),
)
def update_config(
    body: AdapterConfigUpdate,
    request: Request,
    response: Response,
    adapter_id: str = ADAPTER_ID_PATH,
    context: AuthContext = Security(authorize, scopes=[Scope.PLATFORMS_WRITE]),
    db: Session = Depends(get_db),
) -> AdapterConfig:
    """Needs If-Match. Administrators only."""
    _require_administrator(context, "Adapter settings")
    adapter = _load(db, adapter_id)
    check_if_match(request, _etag(adapter), "adapter")
    with _adapter_errors(context):
        adapter_config.update(db, adapter, body.settings, actor=context.credential)
        db.commit()
        response.headers["ETag"] = _etag(adapter)
        return _config(adapter)


@router.post(
    "/{adapter_id}/setup",
    response_model=AdapterConfig,
    summary="Set up settings",
    responses=error_responses(
        NOT_ADMINISTRATOR,
        NOT_FOUND,
        CONCURRENT_CHANGE,
        IF_MATCH_ERRORS,
        ADAPTER_BROKEN,
        {400: "The adapter has no setup, or rejected the inputs."},
    ),
)
def setup_config(
    body: AdapterSetup,
    request: Request,
    response: Response,
    adapter_id: str = ADAPTER_ID_PATH,
    context: AuthContext = Security(authorize, scopes=[Scope.PLATFORMS_WRITE]),
    db: Session = Depends(get_db),
) -> AdapterConfig:
    """Runs the adapter's setup and replaces its settings. Needs If-Match.

    Administrators only. The inputs are listed in its config's setup.
    """
    _require_administrator(context, "Adapter settings")
    adapter = _load(db, adapter_id)
    check_if_match(request, _etag(adapter), "adapter")
    # End the read transaction before the adapter runs. A change made meanwhile
    # still fails the save, which checks the adapter's version.
    db.commit()
    with _adapter_errors(context):
        adapter_config.setup(db, adapter, body.inputs, actor=context.credential)
        db.commit()
        response.headers["ETag"] = _etag(adapter)
        return _config(adapter)


def _require_allowed(url: str) -> None:
    if not manager.is_allowed_github_url(url):
        raise ApiError(
            400,
            "Only GitHub repositories of orgs in PLATFORMS_GITHUB_ORGS can be used.",
        )


def _queue(
    db: Session, request: Request, response: Response, **job_fields
) -> AdapterJobInfo:
    try:
        job = jobs.create(db, **job_fields)
    except jobs.JobBusyError as e:
        raise ApiError(409, str(e)) from None
    db.commit()
    try:
        run_adapter_job.delay(str(job.id))
    except Exception as e:
        # Fail the job now. Otherwise it stays active and blocks every other job for
        # the adapter until cleanup fails it as abandoned.
        jobs.finish(db, job.id, state="failed", log=[f"Queueing failed: {e}"])
        db.commit()
        raise ApiError(
            503, "The job queue is unavailable. Try again later.", log=str(e)
        ) from e
    response.headers["Location"] = str(request.url_for("get_job", job_id=job.id))
    return AdapterJobInfo.model_validate(job)


@router.post(
    "",
    response_model=AdapterJobInfo,
    status_code=202,
    summary="Install adapter",
    responses=error_responses(
        NOT_ADMINISTRATOR,
        QUEUE_DOWN,
        {
            400: "source_url isn't a GitHub repository of an org in "
            "PLATFORMS_GITHUB_ORGS.",
            409: "Already installed, or an install of it is already running.",
        },
    ),
)
def install_adapter(
    body: AdapterInstall,
    request: Request,
    response: Response,
    context: AuthContext = Security(authorize, scopes=[Scope.PLATFORMS_WRITE]),
    db: Session = Depends(get_db),
) -> AdapterJobInfo:
    """Queues an install; poll the job at Location. Administrators only."""
    _require_administrator(context, "Installing and updating adapters")
    _require_allowed(body.source_url)
    adapter_id = manager.adapter_id(body.source_url)
    if db.get(PlatformAdapter, adapter_id) is not None:
        raise ApiError(409, "This adapter is already installed. Update it instead.")
    return _queue(
        db,
        request,
        response,
        adapter_id=adapter_id,
        action="install",
        source_url=body.source_url,
        tag=body.tag,
        requested_by=context.credential.id,
    )


@router.post(
    "/{adapter_id}/update",
    response_model=AdapterJobInfo,
    status_code=202,
    summary="Update adapter",
    responses=error_responses(
        NOT_ADMINISTRATOR,
        QUEUE_DOWN,
        NOT_FOUND,
        {
            400: "The adapter's source isn't a GitHub repository of an org in "
            "PLATFORMS_GITHUB_ORGS.",
            409: "An install or update of it is already running.",
        },
    ),
)
def update_adapter_version(
    body: AdapterUpgrade,
    request: Request,
    response: Response,
    adapter_id: str = ADAPTER_ID_PATH,
    context: AuthContext = Security(authorize, scopes=[Scope.PLATFORMS_WRITE]),
    db: Session = Depends(get_db),
) -> AdapterJobInfo:
    """Queues a move to a version tag; poll the job at Location. Administrators only."""
    _require_administrator(context, "Installing and updating adapters")
    adapter = _load(db, adapter_id)
    _require_allowed(adapter.source_url)
    return _queue(
        db,
        request,
        response,
        adapter_id=adapter.id,
        action="update",
        source_url=adapter.source_url,
        tag=body.tag,
        from_commit=adapter.commit,
        requested_by=context.credential.id,
    )


@router.get(
    "/jobs/{job_id}",
    response_model=AdapterJobInfo,
    summary="Get job",
    responses=error_responses({404: "No job with that ID."}),
)
def get_job(
    job_id: uuid.UUID,
    context: AuthContext = Security(authorize, scopes=[Scope.PLATFORMS_WRITE]),
    db: Session = Depends(get_db),
) -> AdapterJobInfo:
    """Poll until the state is succeeded or failed. Scope: platforms:write."""
    job = db.get(jobs.PlatformAdapterJob, job_id)
    if job is None:
        raise ApiError(404, "Job not found.")
    return AdapterJobInfo.model_validate(job)


@router.get(
    "/{adapter_id}/jobs",
    response_model=list[AdapterJobInfo],
    summary="List jobs",
)
def list_jobs(
    adapter_id: str = ADAPTER_ID_PATH,
    context: AuthContext = Security(authorize, scopes=[Scope.PLATFORMS_WRITE]),
    db: Session = Depends(get_db),
) -> list[AdapterJobInfo]:
    """The last 20 installs and updates, newest first. Scope: platforms:write."""
    return [
        AdapterJobInfo.model_validate(job)
        for job in jobs.list_for_adapter(db, adapter_id)
    ]
