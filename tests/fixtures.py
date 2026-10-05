# SPDX-License-Identifier: GPL-3.0-only
"""Shared fixtures, loaded by conftest.py once the test environment is set."""

import pytest
from argon2 import PasswordHasher
from fastapi import FastAPI
from fastapi.testclient import TestClient

import publisher.models  # noqa: F401  (registers every table on Base.metadata)
from publisher import credentials, db
from publisher.api.rest import app as app_module
from publisher.api.rest.v1 import routes
from publisher.db import Base
from tests.helpers import USERNAME, create_credential


@pytest.fixture
def test_db():
    """A fresh in-memory database with every table."""
    db.dispose_engine()
    Base.metadata.create_all(db.get_engine())
    yield
    db.dispose_engine()


@pytest.fixture
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


@pytest.fixture
def password():
    """Password of USERNAME, an administrator."""
    return create_credential(USERNAME)
