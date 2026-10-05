# SPDX-License-Identifier: GPL-3.0-only

import base64
from collections.abc import Iterable

import pytest
from argon2 import PasswordHasher
from fastapi import FastAPI
from fastapi.testclient import TestClient

import app as app_module
import publisher.models  # noqa: F401  (registers every table on Base.metadata)
import rest_services.v1.routes as routes
from publisher import db
from publisher.db import Base
from publisher.models import credential as credentials
from publisher.models.credential import ALL_SCOPES, Scope

USERNAME = "ops"


@pytest.fixture(autouse=True)
def use_test_db():
    db.dispose_engine()
    Base.metadata.create_all(db.get_engine())
    yield
    db.dispose_engine()


@pytest.fixture(autouse=True)
def fast_hasher(monkeypatch):
    # Default Argon2 cost is too slow for tests.
    monkeypatch.setattr(
        credentials,
        "password_hasher",
        PasswordHasher(time_cost=1, memory_cost=1024, parallelism=1),
    )
    credentials._dummy_hash.cache_clear()
    yield
    credentials._dummy_hash.cache_clear()


@pytest.fixture
def app():
    test_app = FastAPI()
    for exc_class, handler in app_module.app.exception_handlers.items():
        test_app.add_exception_handler(exc_class, handler)
    test_app.include_router(routes.router, prefix="/v1")
    return test_app


@pytest.fixture
def client(app):
    # https, or the Secure cookie isn't sent back.
    return TestClient(app, base_url="https://testserver")


def create_credential(username: str, scopes: Iterable[str] = ALL_SCOPES) -> str:
    with db.get_session() as session:
        _, password = credentials.create(
            session, username, frozenset(Scope(s) for s in scopes)
        )
    return password


@pytest.fixture
def password():
    """Password of USERNAME, an administrator."""
    return create_credential(USERNAME)


def basic_auth(username: str, password: str) -> dict[str, str]:
    token = base64.b64encode(f"{username}:{password}".encode()).decode()
    return {"Authorization": f"Basic {token}"}


def login(client: TestClient, password: str, username: str = USERNAME):
    return client.post(
        "/v1/auth/login", json={"username": username, "password": password}
    )


def can_log_in(username: str, password: str) -> bool:
    with db.get_session() as session:
        return credentials.authenticate(session, username, password) is not None
