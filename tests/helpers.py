# SPDX-License-Identifier: GPL-3.0-only
"""Helpers for tests that create credentials and log in."""

import base64
from collections.abc import Iterable

from fastapi.testclient import TestClient

from publisher import credentials, db
from publisher.models.credential import ALL_SCOPES, Scope

USERNAME = "ops"


def create_credential(username: str, scopes: Iterable[str] = ALL_SCOPES) -> str:
    with db.get_session() as session:
        _, password = credentials.create(
            session, username, frozenset(Scope(s) for s in scopes)
        )
    return password


def basic_auth(username: str, password: str) -> dict[str, str]:
    token = base64.b64encode(f"{username}:{password}".encode()).decode()
    return {"Authorization": f"Basic {token}"}


def get_etag(client: TestClient, headers: dict[str, str], username: str) -> str:
    response = client.get(f"/v1/creds/{username}", headers=headers)
    assert response.status_code == 200, response.text
    return response.headers["etag"]


def login(client: TestClient, password: str, username: str = USERNAME):
    return client.post(
        "/v1/auth/login", json={"username": username, "password": password}
    )


def can_log_in(username: str, password: str) -> bool:
    with db.get_session() as session:
        return credentials.authenticate(session, username, password) is not None
