# SPDX-License-Identifier: GPL-3.0-only

import dataclasses
import datetime

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import update

import admin_auth_config
import app as app_module
import rest_services.v1.routes as routes
from db import get_session
from db_types import utc_now
from models import admin_user as admin_users
from models.admin_session import AdminSession
from rest_services.v1.auth import require_admin
from tests.admin_fixtures import *  # noqa: F401,F403
from tests.admin_fixtures import ADMIN_EMAIL, login

WEB_ORIGIN = "https://web.example.net"


def _set_settings(monkeypatch, **changes):
    monkeypatch.setattr(
        admin_auth_config,
        "settings",
        dataclasses.replace(admin_auth_config.settings, **changes),
    )


def _age_sessions(**columns):
    with get_session() as db:
        db.execute(update(AdminSession).values(**columns))


def _ago(delta):
    return utc_now() - delta


def test_login_sets_hardened_cookie_and_returns_csrf(client, admin_password):
    response = login(client, admin_password)

    assert response.status_code == 200
    body = response.json()
    assert body["email"] == ADMIN_EMAIL
    assert body["auth_method"] == "session"
    assert body["csrf_token"]
    assert response.headers["cache-control"] == "private, no-store"

    cookie = response.headers["set-cookie"]
    assert cookie.startswith("relaysms_admin_session=")
    for flag in ("HttpOnly", "Secure", "SameSite=strict", "Path=/v1", "Max-Age=43200"):
        assert flag in cookie


@pytest.mark.parametrize(
    "email, password_suffix",
    [(ADMIN_EMAIL, "x"), ("nobody@example.org", "")],
)
def test_login_rejects_bad_credentials_generically(
    client, admin_password, email, password_suffix
):
    response = login(client, admin_password + password_suffix, email=email)

    assert response.status_code == 401
    assert response.json()["error"] == "Invalid email or password."
    assert "www-authenticate" not in response.headers
    assert "set-cookie" not in response.headers


@pytest.mark.parametrize(
    "headers, status",
    [
        ({}, 200),
        ({"Origin": "https://testserver"}, 200),
        ({"Origin": WEB_ORIGIN}, 200),
        ({"Origin": "https://evil.example"}, 403),
        ({"Referer": "https://evil.example/page"}, 403),
        ({"Origin": "null"}, 403),
    ],
)
def test_login_origin_check(client, admin_password, monkeypatch, headers, status):
    _set_settings(monkeypatch, web_origins=[WEB_ORIGIN])

    response = client.post(
        "/v1/auth/login",
        json={"email": ADMIN_EMAIL, "password": admin_password},
        headers=headers,
    )
    assert response.status_code == status


def test_me_returns_same_csrf_token_as_login(client, admin_password):
    csrf = login(client, admin_password).json()["csrf_token"]

    response = client.get("/v1/auth/me")

    assert response.status_code == 200
    assert response.json()["csrf_token"] == csrf
    assert response.json()["auth_method"] == "session"


def test_me_unauthenticated_is_401_without_basic_prompt(client):
    response = client.get("/v1/auth/me")

    assert response.status_code == 401
    # A Basic challenge would make browsers show a login dialog.
    assert "www-authenticate" not in response.headers


def test_logout_rejects_foreign_origin_even_with_csrf(client, admin_password):
    csrf = login(client, admin_password).json()["csrf_token"]

    response = client.post(
        "/v1/auth/logout",
        headers={"X-CSRF-Token": csrf, "Origin": "https://evil.example"},
    )
    assert response.status_code == 403


def test_logout_ends_session(client, admin_password):
    csrf = login(client, admin_password).json()["csrf_token"]
    token = client.cookies.get("relaysms_admin_session")

    response = client.post("/v1/auth/logout", headers={"X-CSRF-Token": csrf})

    assert response.status_code == 204
    assert "Max-Age=0" in response.headers["set-cookie"]
    replay = client.get(
        "/v1/auth/me", headers={"Cookie": f"relaysms_admin_session={token}"}
    )
    assert replay.status_code == 401


def test_csrf_applies_to_any_admin_write(app, client, admin_password):
    @app.post("/v1/admin-write")
    def admin_write(context=Depends(require_admin)):
        return {"ok": True}

    csrf = login(client, admin_password).json()["csrf_token"]

    assert client.post("/v1/admin-write").status_code == 403
    wrong = client.post("/v1/admin-write", headers={"X-CSRF-Token": "wrong"})
    assert wrong.status_code == 403
    ok = client.post("/v1/admin-write", headers={"X-CSRF-Token": csrf})
    assert ok.status_code == 200


@pytest.mark.parametrize(
    "columns",
    [
        {"last_seen_at": _ago(datetime.timedelta(minutes=31))},
        {"expires_at": _ago(datetime.timedelta(seconds=1))},
    ],
    ids=["idle", "absolute"],
)
def test_expired_session_is_rejected(client, admin_password, columns):
    login(client, admin_password)
    _age_sessions(**columns)

    assert client.get("/v1/auth/me").status_code == 401


def test_active_session_slides_idle_window(client, admin_password):
    login(client, admin_password)
    _age_sessions(last_seen_at=_ago(datetime.timedelta(minutes=29)))

    assert client.get("/v1/auth/me").status_code == 200
    with get_session() as db:
        last_seen = db.query(AdminSession.last_seen_at).scalar()
    assert last_seen > _ago(datetime.timedelta(minutes=1))


@pytest.mark.parametrize(
    "change",
    [
        lambda db: admin_users.reset_password(db, ADMIN_EMAIL),
        lambda db: admin_users.set_active(db, ADMIN_EMAIL, False),
        lambda db: admin_users.delete_admin(db, ADMIN_EMAIL),
    ],
    ids=["reset-password", "disable", "delete"],
)
def test_account_changes_end_sessions(client, admin_password, change):
    login(client, admin_password)
    with get_session() as db:
        change(db)

    assert client.get("/v1/auth/me").status_code == 401
    with get_session() as db:
        assert db.query(AdminSession).count() == 0


def test_samesite_none_forces_secure_cookie(monkeypatch):
    monkeypatch.setenv("ADMIN_SESSION_COOKIE_SAMESITE", "none")
    monkeypatch.setenv("ADMIN_SESSION_COOKIE_SECURE", "false")

    assert admin_auth_config.load_settings().cookie_secure is True


def test_wildcard_web_origin_is_rejected(monkeypatch):
    monkeypatch.setenv("ADMIN_WEB_ORIGINS", "*")

    with pytest.raises(ValueError):
        admin_auth_config.load_settings()


@pytest.fixture
def cors_client(monkeypatch):
    _set_settings(monkeypatch, web_origins=[WEB_ORIGIN])
    cors_app = FastAPI()
    cors_app.include_router(routes.router, prefix="/v1")
    app_module.configure_cors(cors_app, admin_auth_config.settings)
    return TestClient(cors_app, base_url="https://testserver")


def test_cors_allows_configured_origin_with_credentials(cors_client):
    response = cors_client.options(
        "/v1/auth/login",
        headers={
            "Origin": WEB_ORIGIN,
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type,x-csrf-token",
        },
    )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == WEB_ORIGIN
    assert response.headers["access-control-allow-credentials"] == "true"


def test_cleanup_deletes_only_expired_sessions(client, admin_password):
    from models import admin_session as admin_sessions

    for _ in range(3):
        login(client, admin_password)
    with get_session() as db:
        idle, expired, live = db.query(AdminSession).order_by(AdminSession.id).all()
        idle.last_seen_at = _ago(datetime.timedelta(minutes=31))
        expired.expires_at = _ago(datetime.timedelta(seconds=1))
        live_id = live.id

    with get_session() as db:
        admin = admin_users.get_by_email(db, ADMIN_EMAIL)
        assert admin_sessions.count_active_by_admin(db) == {admin.id: 1}
        assert admin_sessions.delete_expired(db) == 2
        assert [s.id for s in db.query(AdminSession).all()] == [live_id]


@pytest.mark.parametrize(
    "url, error",
    [
        (
            "/v1/stats/publications?status=bad%0Aline",
            "query.status: String should match pattern '^[a-zA-Z0-9_-]+$', "
            "got 'bad\\nline'",
        ),
        (
            "/v1/stats/publications?limit=" + "9" * 80,
            "query.limit: Input should be less than or equal to 200, "
            f"got '{'9' * 50}...'",
        ),
    ],
)
def test_validation_errors_echo_query_input(client, url, error):
    response = client.get(url)

    assert response.status_code == 422
    assert response.json() == {"error": error}
