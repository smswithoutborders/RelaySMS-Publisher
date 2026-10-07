# SPDX-License-Identifier: GPL-3.0-only
"""Credential management endpoints."""

import logging
from contextlib import contextmanager

from fastapi import APIRouter, Depends, HTTPException, Path, Request, Response, Security
from sqlalchemy.orm import Session

from publisher import credentials
from publisher.api.rest.v1.auth import AuthContext, authorize
from publisher.api.rest.v1.errors import (
    CONCURRENT_CHANGE,
    IF_MATCH_ERRORS,
    ApiError,
    error_responses,
)
from publisher.api.rest.v1.params import check_if_match, etag
from publisher.api.rest.v1.schemas import (
    CredentialCreate,
    CredentialInfo,
    CredentialUpdate,
    CredentialWithPassword,
)
from publisher.credentials import (
    CredentialConflictError,
    CredentialError,
    CredentialExistsError,
    CredentialPermissionError,
)
from publisher.db import get_db
from publisher.models import audit_event
from publisher.models import credential_session as credential_sessions
from publisher.models.audit_event import AuditAction, AuditOutcome
from publisher.models.credential import MAX_USERNAME_LENGTH, Credential, Scope

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/creds", tags=["Credentials"])

USERNAME_PATH = Path(..., max_length=MAX_USERNAME_LENGTH)
NOT_FOUND = {404: "No credential with that username."}
CHANGE_TARGET_403 = {
    403: "Also when changing your own credential or one with scopes you don't hold."
}
SCOPE_ERROR = "an unknown scope, or a scope without the one it requires."


def _etag(credential: Credential) -> str:
    return etag(credential.id, credential.version)


@contextmanager
def _model_errors(
    db: Session,
    actor: Credential,
    action: AuditAction,
    target: Credential | None = None,
    details: dict | None = None,
):
    by = f"actor {actor.id}"
    try:
        yield
    except CredentialExistsError as e:
        raise ApiError(
            409, "That username is already taken.", log=f"{by}: {e}"
        ) from None
    except CredentialConflictError as e:
        raise ApiError(
            409,
            "The credential was changed by another request. Reload and try again.",
            log=f"{by}: {e}",
        ) from None
    except CredentialPermissionError as e:
        # Keep the denial, not the change.
        db.rollback()
        audit_event.record(
            db,
            action,
            actor=actor,
            target=target,
            outcome=AuditOutcome.DENIED,
            details={**(details or {}), "reason": str(e)},
        )
        db.commit()
        raise ApiError(403, f"{e}.", log=f"{by}: {e}") from None
    except CredentialError as e:
        raise ApiError(400, str(e), log=by) from None


def _load(db: Session, username: str) -> Credential:
    credential = credentials.get_by_username(db, username)
    if credential is None:
        raise ApiError(404, "Credential not found.")
    return credential


def _info(credential: Credential, active_sessions: int) -> CredentialInfo:
    return CredentialInfo(
        username=credential.username,
        active=credential.is_active,
        scopes=sorted(credential.scopes),
        administrator=credential.is_administrator,
        created_at=credential.created_at,
        last_login_at=credential.last_login_at,
        active_sessions=active_sessions,
    )


def _respond(db: Session, response: Response, credential: Credential) -> CredentialInfo:
    response.headers["ETag"] = _etag(credential)
    return _info(credential, credential_sessions.count_active(db, credential.id))


@router.get("", response_model=list[CredentialInfo], summary="List credentials")
def list_credentials(
    context: AuthContext = Security(authorize, scopes=[Scope.CREDS_READ]),
    db: Session = Depends(get_db),
) -> list[CredentialInfo]:
    """Scope: creds:read."""
    sessions = credential_sessions.count_active_by_credential(db)
    return [
        _info(credential, sessions.get(credential.id, 0))
        for credential in credentials.list_credentials(db)
    ]


@router.get(
    "/{username}",
    response_model=CredentialInfo,
    summary="Get credential",
    responses=error_responses(NOT_FOUND),
)
def get_credential(
    response: Response,
    username: str = USERNAME_PATH,
    context: AuthContext = Security(authorize, scopes=[Scope.CREDS_READ]),
    db: Session = Depends(get_db),
) -> CredentialInfo:
    """Returns the ETag to send as If-Match. Scope: creds:read."""
    return _respond(db, response, _load(db, username))


@router.post(
    "",
    response_model=CredentialWithPassword,
    status_code=201,
    summary="Create credential",
    responses=error_responses(
        {
            400: f"Invalid username, {SCOPE_ERROR}",
            403: "Also when granting scopes you don't hold.",
            409: "That username is already taken.",
        }
    ),
)
def create_credential(
    body: CredentialCreate,
    request: Request,
    response: Response,
    context: AuthContext = Security(authorize, scopes=[Scope.CREDS_WRITE]),
    db: Session = Depends(get_db),
) -> CredentialWithPassword:
    """The generated password is shown only in this response. Scope: creds:write."""
    with _model_errors(
        db,
        context.credential,
        AuditAction.CREDS_CREATE,
        details={"username": body.username},
    ):
        credential, password = credentials.create(
            db, body.username, body.scopes, actor=context.credential
        )
    db.commit()

    logger.info(
        "Credential %s created credential %s with scopes %s.",
        context.credential.id,
        credential.id,
        ",".join(sorted(credential.scopes)),
    )
    response.headers["Location"] = str(
        request.url_for("get_credential", username=credential.username)
    )
    info = _respond(db, response, credential)
    return CredentialWithPassword(**info.model_dump(), password=password)


@router.patch(
    "/{username}",
    response_model=CredentialInfo,
    summary="Update credential",
    responses=error_responses(
        NOT_FOUND,
        CONCURRENT_CHANGE,
        IF_MATCH_ERRORS,
        {
            400: f"Nothing to change, {SCOPE_ERROR}",
            403: "Also when changing your own credential or one with scopes you "
            "don't hold, or granting scopes you don't hold.",
        },
    ),
)
def update_credential(
    body: CredentialUpdate,
    request: Request,
    response: Response,
    username: str = USERNAME_PATH,
    context: AuthContext = Security(authorize, scopes=[Scope.CREDS_WRITE]),
    db: Session = Depends(get_db),
) -> CredentialInfo:
    """Deactivating ends its sessions. Needs If-Match. Scope: creds:write."""
    if body.scopes is None and body.active is None:
        raise HTTPException(status_code=400, detail="Nothing to change.")

    credential = _load(db, username)
    check_if_match(request, _etag(credential), "credential")
    with _model_errors(db, context.credential, AuditAction.CREDS_UPDATE, credential):
        credentials.update(
            db,
            credential,
            scopes=body.scopes,
            active=body.active,
            actor=context.credential,
        )
    db.commit()

    logger.info(
        "Credential %s updated credential %s: scopes %s, active %s.",
        context.credential.id,
        credential.id,
        ",".join(sorted(credential.scopes)),
        credential.is_active,
    )
    return _respond(db, response, credential)


@router.post(
    "/{username}/reset-password",
    response_model=CredentialWithPassword,
    summary="Reset password",
    responses=error_responses(
        CHANGE_TARGET_403, NOT_FOUND, CONCURRENT_CHANGE, IF_MATCH_ERRORS
    ),
)
def reset_credential_password(
    request: Request,
    response: Response,
    username: str = USERNAME_PATH,
    context: AuthContext = Security(authorize, scopes=[Scope.CREDS_WRITE]),
    db: Session = Depends(get_db),
) -> CredentialWithPassword:
    """New password shown once; sessions end. Needs If-Match. Scope: creds:write."""
    credential = _load(db, username)
    check_if_match(request, _etag(credential), "credential")
    with _model_errors(
        db, context.credential, AuditAction.CREDS_RESET_PASSWORD, credential
    ):
        password = credentials.reset_password(db, credential, actor=context.credential)
    db.commit()

    logger.info(
        "Credential %s reset the password of credential %s.",
        context.credential.id,
        credential.id,
    )
    info = _respond(db, response, credential)
    return CredentialWithPassword(**info.model_dump(), password=password)


@router.post(
    "/{username}/revoke-sessions",
    status_code=204,
    summary="Revoke sessions",
    responses=error_responses(CHANGE_TARGET_403, NOT_FOUND, CONCURRENT_CHANGE),
)
def revoke_credential_sessions(
    username: str = USERNAME_PATH,
    context: AuthContext = Security(authorize, scopes=[Scope.CREDS_WRITE]),
    db: Session = Depends(get_db),
) -> Response:
    """Logs it out everywhere; Basic auth still works. Scope: creds:write."""
    credential = _load(db, username)
    with _model_errors(
        db, context.credential, AuditAction.CREDS_REVOKE_SESSIONS, credential
    ):
        credentials.revoke_sessions(db, credential, actor=context.credential)
    db.commit()

    logger.info(
        "Credential %s ended the sessions of credential %s.",
        context.credential.id,
        credential.id,
    )
    return Response(status_code=204)


@router.delete(
    "/{username}",
    status_code=204,
    summary="Delete credential",
    responses=error_responses(
        CHANGE_TARGET_403, NOT_FOUND, CONCURRENT_CHANGE, IF_MATCH_ERRORS
    ),
)
def delete_credential(
    request: Request,
    username: str = USERNAME_PATH,
    context: AuthContext = Security(authorize, scopes=[Scope.CREDS_WRITE]),
    db: Session = Depends(get_db),
) -> Response:
    """Needs If-Match. Scope: creds:write."""
    credential = _load(db, username)
    check_if_match(request, _etag(credential), "credential")
    credential_id = credential.id
    with _model_errors(db, context.credential, AuditAction.CREDS_DELETE, credential):
        credentials.delete(db, credential, actor=context.credential)
    db.commit()

    logger.info(
        "Credential %s deleted credential %s.", context.credential.id, credential_id
    )
    return Response(status_code=204)
