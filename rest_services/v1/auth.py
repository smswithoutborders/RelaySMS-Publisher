# SPDX-License-Identifier: GPL-3.0-only
"""Session cookie and HTTP Basic auth, scope checks, and the /auth endpoints."""

import logging
from dataclasses import dataclass
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.security import (
    APIKeyCookie,
    HTTPBasic,
    HTTPBasicCredentials,
    SecurityScopes,
)
from sqlalchemy.orm import Session

from publisher.config import AuthConfig
from publisher.credentials import authenticate, record_login
from publisher.db import get_db
from publisher.models import credential_session as credential_sessions
from publisher.models.credential import Credential
from publisher.models.credential_session import CredentialSession
from rest_services.v1.errors import ApiError
from rest_services.v1.schemas import CurrentCredential, LoginRequest

SESSION_COOKIE_NAME = "relaysms_session"
SESSION_COOKIE_PATH = "/v1"
SESSION_COOKIE_SAMESITE = "strict"
BASIC_REALM = "relaysms"
# Basic auth runs on every request, so last_login_at writes are throttled.
BASIC_LOGIN_RECORD_INTERVAL_SECONDS = 300
SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})
PRIVATE_CACHE_CONTROL = "private, no-store"

logger = logging.getLogger(__name__)

auth_config = AuthConfig.get()

router = APIRouter(prefix="/auth", tags=["Auth"])

# Read the Basic header and session cookie, and list both in the API docs.
basic_auth = HTTPBasic(realm=BASIC_REALM, auto_error=False)
session_cookie = APIKeyCookie(
    name=SESSION_COOKIE_NAME,
    scheme_name="SessionCookie",
    description="Set by POST /v1/auth/login.",
    auto_error=False,
)


@dataclass(frozen=True)
class AuthContext:
    credential: Credential
    session: CredentialSession | None = None


def set_session_cookie(response: Response, raw_token: str) -> None:
    response.set_cookie(
        SESSION_COOKIE_NAME,
        raw_token,
        max_age=int(auth_config.max_age.total_seconds()),
        path=SESSION_COOKIE_PATH,
        secure=auth_config.cookie_secure,
        httponly=True,
        samesite=SESSION_COOKIE_SAMESITE,
    )


def clear_session_cookie(response: Response) -> None:
    response.delete_cookie(
        SESSION_COOKIE_NAME,
        path=SESSION_COOKIE_PATH,
        secure=auth_config.cookie_secure,
        httponly=True,
        samesite=SESSION_COOKIE_SAMESITE,
    )


def _clear_cookie_header() -> dict[str, str]:
    response = Response()
    clear_session_cookie(response)
    return {"Set-Cookie": response.headers["set-cookie"]}


def _basic_challenge(detail: str) -> HTTPException:
    return HTTPException(
        status_code=401,
        detail=detail,
        headers={"WWW-Authenticate": f'Basic realm="{BASIC_REALM}", charset="UTF-8"'},
    )


def _request_origin(request: Request) -> str | None:
    origin = request.headers.get("Origin")
    if origin and origin != "null":
        return origin.rstrip("/")
    referer = request.headers.get("Referer")
    if referer:
        parts = urlsplit(referer)
        if parts.scheme and parts.netloc:
            return f"{parts.scheme}://{parts.netloc}"
    return origin


def check_origin(request: Request) -> None:
    origin = _request_origin(request)
    # Browsers send Origin on cross-origin POSTs; none means a non-browser client.
    if origin is None:
        return
    own_origin = f"{request.url.scheme}://{request.url.netloc}"
    if origin != own_origin and origin not in auth_config.web_origins:
        raise ApiError(403, "Origin not allowed.", log=f"origin {origin!r} not allowed")


def authenticate_request(
    request: Request,
    response: Response,
    basic: HTTPBasicCredentials | None = Depends(basic_auth),
    raw_token: str | None = Depends(session_cookie),
    db: Session = Depends(get_db),
) -> AuthContext:
    response.headers["Cache-Control"] = PRIVATE_CACHE_CONTROL
    if raw_token:
        credential_session = credential_sessions.get_active(db, raw_token)
        if credential_session is None:
            raise HTTPException(
                status_code=401,
                detail="Session expired or invalid. Please log in again.",
                headers=_clear_cookie_header(),
            )
        if request.method not in SAFE_METHODS:
            check_origin(request)
        return AuthContext(
            credential=credential_session.credential, session=credential_session
        )

    if basic:
        credential = authenticate(db, basic.username, basic.password)
        if credential is None:
            raise _basic_challenge("Invalid username or password.")
        record_login(
            db, credential, min_interval_seconds=BASIC_LOGIN_RECORD_INTERVAL_SECONDS
        )
        return AuthContext(credential=credential)

    # No Basic challenge, because browsers would show their own login dialog.
    raise HTTPException(status_code=401, detail="Authentication required.")


def authorize(
    security_scopes: SecurityScopes,
    context: AuthContext = Depends(authenticate_request),
) -> AuthContext:
    """Use as Security(authorize, scopes=[...]) to require every listed scope."""
    require_scopes(context, *security_scopes.scopes)
    return context


def require_scopes(context: AuthContext, *scopes: str) -> None:
    missing = sorted(set(scopes) - context.credential.scopes)
    if missing:
        raise ApiError(
            403,
            f"Missing scope: {', '.join(missing)}.",
            log=f"credential {context.credential.id} lacks {', '.join(missing)}",
        )


def _current_credential(
    credential: Credential, session: CredentialSession | None = None
) -> CurrentCredential:
    return CurrentCredential(
        username=credential.username,
        scopes=sorted(credential.scopes),
        administrator=credential.is_administrator,
        auth_method="basic" if session is None else "session",
        expires_at=session.expires_at if session else None,
    )


@router.post("/login", response_model=CurrentCredential, summary="Log in")
def login(
    body: LoginRequest,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
) -> CurrentCredential:
    """Sets an HttpOnly session cookie."""
    check_origin(request)

    credential = authenticate(db, body.username, body.password)
    if credential is None:
        raise HTTPException(status_code=401, detail="Invalid username or password.")

    credential_session, raw_token = credential_sessions.create(
        db,
        credential,
        max_age=auth_config.max_age,
        user_agent=request.headers.get("User-Agent"),
    )
    record_login(db, credential)
    db.commit()

    set_session_cookie(response, raw_token)
    response.headers["Cache-Control"] = PRIVATE_CACHE_CONTROL
    logger.info("Credential %s logged in.", credential.id)
    return _current_credential(credential, credential_session)


@router.post("/logout", status_code=204, summary="Log out")
def logout(
    context: AuthContext = Depends(authenticate_request),
    db: Session = Depends(get_db),
) -> Response:
    """Ends the cookie session."""
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


@router.get("/me", response_model=CurrentCredential, summary="Current credential")
def me(context: AuthContext = Depends(authenticate_request)) -> CurrentCredential:
    return _current_credential(context.credential, context.session)
