# SPDX-License-Identifier: GPL-3.0-only
"""Credential management endpoints."""

import hashlib
from contextlib import contextmanager
from typing import List

from fastapi import APIRouter, Depends, HTTPException, Path, Request, Response, Security
from sqlalchemy.orm import Session

from db import get_db
from logutils import get_logger
from models import credential as credentials
from models import credential_session as credential_sessions
from models.credential import (
    MAX_USERNAME_LENGTH,
    Credential,
    CredentialConflictError,
    CredentialExistsError,
    CredentialPermissionError,
    Scope,
)
from rest_services.v1.auth import AuthContext, authorize
from rest_services.v1.errors import ApiError
from rest_services.v1.schemas import (
    CredentialCreate,
    CredentialInfo,
    CredentialUpdate,
    CredentialWithPassword,
)

logger = get_logger(__name__)

router = APIRouter(prefix="/creds", tags=["Credentials"])

USERNAME_PATH = Path(..., max_length=MAX_USERNAME_LENGTH)


def _etag(credential: Credential) -> str:
    # An opaque hash of the internal id and the version.
    digest = hashlib.sha256(f"{credential.id}:{credential.version}".encode())
    return f'"{digest.hexdigest()[:32]}"'


def _check_if_match(request: Request, credential: Credential) -> None:
    if_match = request.headers.get("If-Match")
    if if_match is None:
        raise ApiError(428, "If-Match header required.")
    current = _etag(credential)
    if if_match.strip() != current:
        raise ApiError(
            412,
            "This credential has changed since you loaded it. Reload and try again.",
            log=f"credential {credential.id}: If-Match {if_match} != ETag {current}",
        )


@contextmanager
def _model_errors(actor: Credential):
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
        raise ApiError(403, f"{e}.", log=f"{by}: {e}") from None
    except ValueError as e:
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


@router.get("", response_model=List[CredentialInfo], summary="List credentials")
def list_credentials(
    context: AuthContext = Security(authorize, scopes=[Scope.CREDS_READ]),
    db: Session = Depends(get_db),
) -> List[CredentialInfo]:
    """Scope: creds:read."""
    sessions = credential_sessions.count_active_by_credential(db)
    return [
        _info(credential, sessions.get(credential.id, 0))
        for credential in credentials.list_credentials(db)
    ]


@router.get("/{username}", response_model=CredentialInfo, summary="Get credential")
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
)
def create_credential(
    body: CredentialCreate,
    request: Request,
    response: Response,
    context: AuthContext = Security(authorize, scopes=[Scope.CREDS_WRITE]),
    db: Session = Depends(get_db),
) -> CredentialWithPassword:
    """The generated password is shown only once. Scope: creds:write."""
    with _model_errors(context.credential):
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


@router.patch("/{username}", response_model=CredentialInfo, summary="Update credential")
def update_credential(
    body: CredentialUpdate,
    request: Request,
    response: Response,
    username: str = USERNAME_PATH,
    context: AuthContext = Security(authorize, scopes=[Scope.CREDS_WRITE]),
    db: Session = Depends(get_db),
) -> CredentialInfo:
    """Change scopes or active. Needs If-Match. Scope: creds:write."""
    if body.scopes is None and body.active is None:
        raise HTTPException(status_code=400, detail="Nothing to change.")

    credential = _load(db, username)
    _check_if_match(request, credential)
    with _model_errors(context.credential):
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
    _check_if_match(request, credential)
    with _model_errors(context.credential):
        password = credentials.reset_password(db, credential, actor=context.credential)
    db.commit()

    logger.info(
        "Credential %s reset the password of credential %s.",
        context.credential.id,
        credential.id,
    )
    info = _respond(db, response, credential)
    return CredentialWithPassword(**info.model_dump(), password=password)


@router.post("/{username}/revoke-sessions", status_code=204, summary="Revoke sessions")
def revoke_credential_sessions(
    username: str = USERNAME_PATH,
    context: AuthContext = Security(authorize, scopes=[Scope.CREDS_WRITE]),
    db: Session = Depends(get_db),
) -> Response:
    """Scope: creds:write."""
    credential = _load(db, username)
    with _model_errors(context.credential):
        credentials.revoke_sessions(db, credential, actor=context.credential)
    db.commit()

    logger.info(
        "Credential %s ended the sessions of credential %s.",
        context.credential.id,
        credential.id,
    )
    return Response(status_code=204)


@router.delete("/{username}", status_code=204, summary="Delete credential")
def delete_credential(
    request: Request,
    username: str = USERNAME_PATH,
    context: AuthContext = Security(authorize, scopes=[Scope.CREDS_WRITE]),
    db: Session = Depends(get_db),
) -> Response:
    """Needs If-Match. Scope: creds:write."""
    credential = _load(db, username)
    _check_if_match(request, credential)
    credential_id = credential.id
    with _model_errors(context.credential):
        credentials.delete(db, credential, actor=context.credential)
    db.commit()

    logger.info(
        "Credential %s deleted credential %s.", context.credential.id, credential_id
    )
    return Response(status_code=204)
