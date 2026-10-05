# SPDX-License-Identifier: GPL-3.0-only

import datetime

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import update

import app as app_module
import rest_services.v1.routes as routes
from publisher import credentials
from publisher.db import get_session
from publisher.db.types import utc_now
from publisher.models.credential import Scope
from publisher.models.credential_session import CredentialSession
from rest_services.v1 import auth
from rest_services.v1.auth import authenticate_request
from tests.creds_fixtures import *  # noqa: F403
from tests.creds_fixtures import USERNAME, basic_auth, login

WEB_ORIGIN = "https://web.example.net"


def _age_sessions(**columns):
    with get_session() as db:
        db.execute(update(CredentialSession).values(**columns))


def _ago(delta):
    return utc_now() - delta


def test_login_sets_hardened_cookie(client, password):
    response = login(client, password)

    assert response.status_code == 200
    body = response.json()
    assert body["username"] == USERNAME
    assert body["administrator"] is True
    assert set(body["scopes"]) == {scope.value for scope in Scope}
    assert body["auth_method"] == "session"
    assert response.headers["cache-control"] == "private, no-store"

    cookie = response.headers["set-cookie"]
    assert cookie.startswith("relaysms_session=")
    for flag in ("HttpOnly", "Secure", "SameSite=strict", "Path=/v1", "Max-Age=43200"):
        assert flag in cookie


@pytest.mark.parametrize(
    "username, password_suffix",
    [(USERNAME, "x"), ("nobody", "")],
)
def test_login_rejects_bad_credentials_generically(
    client, password, username, password_suffix
):
    response = login(client, password + password_suffix, username=username)

    assert response.status_code == 401
    assert response.json()["error"] == "Invalid username or password."
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
def test_login_origin_check(client, password, set_config, headers, status):
    set_config(auth, "auth_config", web_origins=[WEB_ORIGIN])

    response = client.post(
        "/v1/auth/login",
        json={"username": USERNAME, "password": password},
        headers=headers,
    )
    assert response.status_code == status


def test_me_returns_session_credential(client, password):
    login(client, password)

    response = client.get("/v1/auth/me")

    assert response.status_code == 200
    assert response.json()["username"] == USERNAME
    assert response.json()["auth_method"] == "session"


def test_me_unauthenticated_is_401_without_basic_prompt(client):
    response = client.get("/v1/auth/me")

    assert response.status_code == 401
    # A Basic challenge would make browsers show a login dialog.
    assert "www-authenticate" not in response.headers


def test_logout_ends_session(client, password):
    login(client, password)
    token = client.cookies.get("relaysms_session")

    response = client.post("/v1/auth/logout", headers={"Origin": "https://testserver"})

    assert response.status_code == 204
    assert "Max-Age=0" in response.headers["set-cookie"]
    replay = client.get("/v1/auth/me", headers={"Cookie": f"relaysms_session={token}"})
    assert replay.status_code == 401


def test_origin_check_applies_to_any_session_write(app, client, password, set_config):
    @app.post("/v1/session-write")
    def session_write(context=Depends(authenticate_request)):
        return {"ok": True}

    set_config(auth, "auth_config", web_origins=[WEB_ORIGIN])
    login(client, password)

    # A sibling subdomain is same-site, so SameSite alone would let it through.
    sibling = {"Origin": "https://other.example.net"}
    assert client.post("/v1/session-write", headers=sibling).status_code == 403
    ok = client.post("/v1/session-write", headers={"Origin": WEB_ORIGIN})
    assert ok.status_code == 200


@pytest.mark.parametrize(
    "columns",
    [
        {"last_seen_at": _ago(datetime.timedelta(minutes=31))},
        {"expires_at": _ago(datetime.timedelta(seconds=1))},
    ],
    ids=["idle", "absolute"],
)
def test_expired_session_is_rejected(client, password, columns):
    login(client, password)
    _age_sessions(**columns)

    assert client.get("/v1/auth/me").status_code == 401


def test_active_session_slides_idle_window(client, password):
    login(client, password)
    _age_sessions(last_seen_at=_ago(datetime.timedelta(minutes=29)))

    assert client.get("/v1/auth/me").status_code == 200
    with get_session() as db:
        last_seen = db.query(CredentialSession.last_seen_at).scalar()
    assert last_seen > _ago(datetime.timedelta(minutes=1))


@pytest.mark.parametrize(
    "change",
    [
        lambda db: credentials.reset_password(
            db, credentials.get_or_raise(db, USERNAME)
        ),
        lambda db: credentials.update(
            db, credentials.get_or_raise(db, USERNAME), active=False
        ),
        lambda db: credentials.delete(db, credentials.get_or_raise(db, USERNAME)),
    ],
    ids=["reset-password", "disable", "delete"],
)
def test_account_changes_end_sessions(client, password, change):
    login(client, password)
    with get_session() as db:
        change(db)

    assert client.get("/v1/auth/me").status_code == 401
    with get_session() as db:
        assert db.query(CredentialSession).count() == 0


@pytest.fixture
def cors_client(set_config):
    set_config(auth, "auth_config", web_origins=[WEB_ORIGIN])
    cors_app = FastAPI()
    cors_app.include_router(routes.router, prefix="/v1")
    app_module.configure_cors(cors_app, auth.auth_config)
    return TestClient(cors_app, base_url="https://testserver")


def test_cors_allows_configured_origin_with_credentials(cors_client):
    response = cors_client.options(
        "/v1/auth/login",
        headers={
            "Origin": WEB_ORIGIN,
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type",
        },
    )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == WEB_ORIGIN
    assert response.headers["access-control-allow-credentials"] == "true"


def test_cleanup_deletes_only_expired_sessions(client, password):
    from publisher.models import credential_session as credential_sessions

    for _ in range(3):
        login(client, password)
    with get_session() as db:
        idle, expired, live = (
            db.query(CredentialSession).order_by(CredentialSession.id).all()
        )
        idle.last_seen_at = _ago(datetime.timedelta(minutes=31))
        expired.expires_at = _ago(datetime.timedelta(seconds=1))
        live_id = live.id

    with get_session() as db:
        credential = credentials.get_by_username(db, USERNAME)
        assert credential_sessions.count_active_by_credential(db) == {credential.id: 1}
        assert credential_sessions.delete_expired(db) == 2
        assert [s.id for s in db.query(CredentialSession).all()] == [live_id]


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
def test_validation_errors_echo_query_input(client, password, url, error):
    response = client.get(url, headers=basic_auth(USERNAME, password))

    assert response.status_code == 422
    assert response.json() == {"error": error}
