# SPDX-License-Identifier: GPL-3.0-only
"""Admin auth: web session cookie or HTTP Basic."""

import base64
import binascii
from dataclasses import dataclass
from typing import Optional
from urllib.parse import urlsplit

from fastapi import Depends, HTTPException, Request, Response
from sqlalchemy.orm import Session

import admin_auth_config as config
from db import get_db
from models import admin_session as admin_sessions
from models.admin_session import AdminSession
from models.admin_user import AdminUser, record_login, verify_credentials

SESSION_COOKIE_NAME = "relaysms_admin_session"
SESSION_COOKIE_PATH = "/v1"
CSRF_HEADER_NAME = "X-CSRF-Token"
BASIC_REALM = "relaysms-admin"
# Basic auth runs on every request, so last_login_at writes are throttled.
BASIC_LOGIN_RECORD_INTERVAL_SECONDS = 300
SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})


@dataclass(frozen=True)
class AdminContext:
    admin: AdminUser
    session: Optional[AdminSession] = None
    session_token: Optional[str] = None


def set_session_cookie(response: Response, raw_token: str) -> None:
    response.set_cookie(
        SESSION_COOKIE_NAME,
        raw_token,
        max_age=int(config.settings.max_age.total_seconds()),
        path=SESSION_COOKIE_PATH,
        domain=config.settings.cookie_domain,
        secure=config.settings.cookie_secure,
        httponly=True,
        samesite=config.settings.cookie_samesite,
    )


def clear_session_cookie(response: Response) -> None:
    response.delete_cookie(
        SESSION_COOKIE_NAME,
        path=SESSION_COOKIE_PATH,
        domain=config.settings.cookie_domain,
        secure=config.settings.cookie_secure,
        httponly=True,
        samesite=config.settings.cookie_samesite,
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
    if origin != own_origin and origin not in config.settings.web_origins:
        raise HTTPException(status_code=403, detail="Origin not allowed.")


def _check_csrf(request: Request, raw_token: str) -> None:
    check_origin(request)
    if not admin_sessions.verify_csrf(raw_token, request.headers.get(CSRF_HEADER_NAME)):
        raise HTTPException(status_code=403, detail="Missing or invalid CSRF token.")


def optional_admin(
    request: Request, db: Session = Depends(get_db)
) -> Optional[AdminContext]:
    raw_token = request.cookies.get(SESSION_COOKIE_NAME)
    if raw_token:
        admin_session = admin_sessions.get_active(db, raw_token)
        if admin_session is None:
            raise HTTPException(
                status_code=401,
                detail="Session expired or invalid. Please log in again.",
                headers=_clear_cookie_header(),
            )
        # Checked here so no route skips it. Basic is exempt: not sent cross-site.
        if request.method not in SAFE_METHODS:
            _check_csrf(request, raw_token)
        return AdminContext(
            admin=admin_session.admin_user,
            session=admin_session,
            session_token=raw_token,
        )

    authorization = request.headers.get("Authorization")
    if authorization:
        email, password = _parse_basic(authorization)
        admin = verify_credentials(db, email, password)
        if admin is None:
            raise _basic_challenge("Invalid email or password.")
        record_login(admin, min_interval_seconds=BASIC_LOGIN_RECORD_INTERVAL_SECONDS)
        return AdminContext(admin=admin)

    return None


def require_admin(
    context: Optional[AdminContext] = Depends(optional_admin),
) -> AdminContext:
    if context is None:
        # No Basic challenge: browsers would show their own login dialog.
        raise HTTPException(status_code=401, detail="Authentication required.")
    return context
