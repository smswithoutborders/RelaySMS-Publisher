# SPDX-License-Identifier: GPL-3.0-only

import pytest
from fastapi.testclient import TestClient

from tests.helpers import USERNAME, basic_auth, create_credential, get_etag, login

pytestmark = pytest.mark.usefixtures("test_db", "fast_hasher")


@pytest.fixture
def analyst_session(app):
    """A separate client, since a session cookie takes precedence over Basic auth."""
    session_client = TestClient(app, base_url="https://testserver")
    password = create_credential("analyst", ["stats:publications:read"])
    login(session_client, password, username="analyst")
    assert session_client.get("/v1/auth/me").status_code == 200
    return session_client


@pytest.fixture
def analyst():
    create_credential("analyst", ["stats:publications:read"])
    return "analyst"


def _create(client, admin, username, scopes):
    return client.post(
        "/v1/creds", json={"username": username, "scopes": scopes}, headers=admin
    )


@pytest.mark.parametrize(
    "method, url",
    [
        ("get", "/v1/creds"),
        ("get", "/v1/creds/analyst"),
        ("post", "/v1/creds"),
        ("patch", "/v1/creds/analyst"),
        ("post", "/v1/creds/analyst/reset-password"),
        ("post", "/v1/creds/analyst/revoke-sessions"),
        ("delete", "/v1/creds/analyst"),
    ],
)
def test_endpoints_require_auth_and_scope(client, analyst, method, url):
    assert client.request(method, url).status_code == 401

    headers = basic_auth(
        "viewer", create_credential("viewer", ["stats:publications:read"])
    )
    response = client.request(method, url, headers=headers)
    assert response.status_code == 403
    assert response.json()["error"].startswith("Missing scope: creds:")


def test_list_and_get(client, admin, analyst):
    listed = client.get("/v1/creds", headers=admin)

    assert listed.status_code == 200
    assert listed.headers["cache-control"] == "private, no-store"
    by_name = {item["username"]: item for item in listed.json()}
    assert by_name[USERNAME]["administrator"] is True
    assert by_name["analyst"]["scopes"] == ["stats:publications:read"]

    item = client.get("/v1/creds/ANALYST", headers=admin)
    assert item.json()["username"] == "analyst"
    assert "etag" not in listed.json()[0]
    assert client.get("/v1/creds/nobody", headers=admin).status_code == 404


def test_etags_are_opaque(client, admin, analyst):
    etags = {
        username: get_etag(client, admin, f"/v1/creds/{username}")
        for username in (USERNAME, "analyst")
    }

    # Both are at version 1, yet their etags differ and don't show it.
    assert etags[USERNAME] != etags["analyst"]
    assert all(len(etag) == 34 and etag not in ('"1"', "1") for etag in etags.values())


def test_create_returns_a_working_password_once(client, admin):
    response = _create(client, admin, "Analyst", ["stats:publications:read"])

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["username"] == "analyst"
    assert response.headers["cache-control"] == "private, no-store"
    assert response.headers["location"].endswith("/v1/creds/analyst")
    assert response.headers["etag"] == get_etag(client, admin, "/v1/creds/analyst")

    me = client.get("/v1/auth/me", headers=basic_auth("analyst", body["password"]))
    assert me.json()["scopes"] == ["stats:publications:read"]
    assert "password" not in client.get("/v1/creds/analyst", headers=admin).json()


@pytest.mark.parametrize(
    "username, scopes, status, error",
    [
        (USERNAME, ["stats:publications:read"], 409, "already taken"),
        ("analyst", ["stats:all"], 400, "Unknown scope"),
        ("analyst", ["gc:write"], 400, "requires gc:read"),
        ("a@b.org", ["gc:read"], 400, "Invalid username"),
    ],
)
def test_create_rejects_bad_input(client, admin, username, scopes, status, error):
    response = _create(client, admin, username, scopes)

    assert response.status_code == status
    assert error in response.json()["error"]


def test_managers_cannot_grant_scopes_they_lack(client):
    manager = basic_auth(
        "manager",
        create_credential(
            "manager", ["creds:read", "creds:write", "stats:publications:read"]
        ),
    )

    denied = _create(client, manager, "x-admin", ["platforms:read"])
    allowed = _create(client, manager, "reader", ["stats:publications:read"])

    assert denied.status_code == 403
    assert "platforms:read" in denied.json()["error"]
    assert allowed.status_code == 201


def test_update_requires_a_current_if_match(client, admin, analyst, caplog):
    url = "/v1/creds/analyst"
    body = {"scopes": ["stats:publications:read", "stats:publications:reasons"]}
    etag = get_etag(client, admin, f"/v1/creds/{analyst}")

    missing = client.patch(url, json=body, headers=admin)
    stale = client.patch(url, json=body, headers={**admin, "If-Match": '"999"'})
    ok = client.patch(url, json=body, headers={**admin, "If-Match": etag})

    assert missing.status_code == 428
    assert stale.status_code == 412
    # The client gets a plain message; the comparison goes to the log.
    assert '"999"' not in stale.json()["error"]
    assert 'If-Match "999" != ETag' in caplog.text
    assert ok.status_code == 200, ok.text
    assert ok.json()["scopes"] == body["scopes"]
    assert ok.headers["etag"] != etag


@pytest.mark.parametrize(
    "body, status",
    [({}, 400), ({"email": "x"}, 422)],
    ids=["empty", "unknown-field"],
)
def test_update_rejects_bad_bodies(client, admin, analyst, body, status):
    response = client.patch(
        "/v1/creds/analyst",
        json=body,
        headers={**admin, "If-Match": get_etag(client, admin, f"/v1/creds/{analyst}")},
    )

    assert response.status_code == status


def test_reset_password_replaces_the_old_one(client, admin):
    old = create_credential("analyst", ["stats:publications:read"])

    response = client.post(
        "/v1/creds/analyst/reset-password",
        headers={**admin, "If-Match": get_etag(client, admin, "/v1/creds/analyst")},
    )

    assert response.status_code == 200
    assert response.headers["cache-control"] == "private, no-store"
    new = response.json()["password"]
    assert (
        client.get("/v1/auth/me", headers=basic_auth("analyst", old)).status_code == 401
    )
    assert (
        client.get("/v1/auth/me", headers=basic_auth("analyst", new)).status_code == 200
    )


def test_revoke_sessions(client, admin, analyst_session):
    response = client.post("/v1/creds/analyst/revoke-sessions", headers=admin)

    assert response.status_code == 204
    assert analyst_session.get("/v1/auth/me").status_code == 401


def test_delete(client, admin, analyst):
    url = "/v1/creds/analyst"

    assert client.delete(url, headers=admin).status_code == 428
    response = client.delete(
        url,
        headers={**admin, "If-Match": get_etag(client, admin, f"/v1/creds/{analyst}")},
    )

    assert response.status_code == 204
    assert client.get(url, headers=admin).status_code == 404
