# SPDX-License-Identifier: GPL-3.0-only
"""Admin auth: web session cookie or HTTP Basic."""

import base64
import binascii
from dataclasses import dataclass
from typing import Optional
from urllib.parse import urlsplit

from fastapi import Depends, HTTPException, Request, Response
from sqlalchemy.orm import Session

from config import AdminAuthConfig
from db import get_db
from models import admin_session as admin_sessions
from models.admin_session import AdminSession
from models.admin_user import AdminUser, record_login, verify_credentials

SESSION_COOKIE_NAME = "relaysms_admin_session"
SESSION_COOKIE_PATH = "/v1"
SESSION_COOKIE_SAMESITE = "strict"
BASIC_REALM = "relaysms-admin"
# Basic auth runs on every request, so last_login_at writes are throttled.
BASIC_LOGIN_RECORD_INTERVAL_SECONDS = 300
SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})

admin_config = AdminAuthConfig.get()


@dataclass(frozen=True)
class AdminContext:
    admin: AdminUser
    session: Optional[AdminSession] = None


def set_session_cookie(response: Response, raw_token: str) -> None:
    response.set_cookie(
        SESSION_COOKIE_NAME,
        raw_token,
        max_age=int(admin_config.max_age.total_seconds()),
        path=SESSION_COOKIE_PATH,
        secure=admin_config.cookie_secure,
        httponly=True,
        samesite=SESSION_COOKIE_SAMESITE,
    )


def clear_session_cookie(response: Response) -> None:
    response.delete_cookie(
        SESSION_COOKIE_NAME,
        path=SESSION_COOKIE_PATH,
        secure=admin_config.cookie_secure,
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


def _parse_basic(authorization: str) -> tuple[str, str]:
    scheme, _, encoded = authorization.partition(" ")
    if scheme.lower() != "basic" or not encoded:
        raise _basic_challenge("Unsupported authorization scheme.")
    try:
        decoded = base64.b64decode(encoded.strip(), validate=True).decode("utf-8")
    except (binascii.Error, UnicodeDecodeError):
        raise _basic_challenge("Malformed Basic credentials.") from None
    email, sep, password = decoded.partition(":")
    if not sep:
        raise _basic_challenge("Malformed Basic credentials.")
    return email, password


def _request_origin(request: Request) -> Optional[str]:
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
    if origin != own_origin and origin not in admin_config.web_origins:
        raise HTTPException(status_code=403, detail="Origin not allowed.")


def require_admin(request: Request, db: Session = Depends(get_db)) -> AdminContext:
    raw_token = request.cookies.get(SESSION_COOKIE_NAME)
    if raw_token:
        admin_session = admin_sessions.get_active(db, raw_token)
        if admin_session is None:
            raise HTTPException(
                status_code=401,
                detail="Session expired or invalid. Please log in again.",
                headers=_clear_cookie_header(),
            )
        if request.method not in SAFE_METHODS:
            check_origin(request)
        return AdminContext(admin=admin_session.admin_user, session=admin_session)

    authorization = request.headers.get("Authorization")
    if authorization:
        email, password = _parse_basic(authorization)
        admin = verify_credentials(db, email, password)
        if admin is None:
            raise _basic_challenge("Invalid email or password.")
        record_login(admin, min_interval_seconds=BASIC_LOGIN_RECORD_INTERVAL_SECONDS)
        return AdminContext(admin=admin)

    # No Basic challenge, because browsers would show their own login dialog.
    raise HTTPException(status_code=401, detail="Authentication required.")
