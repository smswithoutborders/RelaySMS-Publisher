# SPDX-License-Identifier: GPL-3.0-only

import base64
import dataclasses
import datetime

import pytest
from argon2 import PasswordHasher
from fastapi import FastAPI
from fastapi.testclient import TestClient

import admin_auth_config
import app as app_module
import db
import models  # noqa: F401  (registers every table on Base.metadata)
import rest_services.v1.routes as routes
from db import Base
from models import admin_user as admin_users

ADMIN_EMAIL = "admin@example.org"


@pytest.fixture(autouse=True)
def use_test_db(monkeypatch):
    monkeypatch.setenv("MODE", "testing")
    db.dispose_engine()
    Base.metadata.create_all(db.get_engine())
    yield
    db.dispose_engine()


@pytest.fixture(autouse=True)
def fast_hasher(monkeypatch):
    # Default Argon2 cost is too slow for tests.
    monkeypatch.setattr(
        admin_users,
        "password_hasher",
        PasswordHasher(time_cost=1, memory_cost=1024, parallelism=1),
    )
    admin_users._dummy_hash.cache_clear()
    yield
    admin_users._dummy_hash.cache_clear()


@pytest.fixture(autouse=True)
def default_admin_settings(monkeypatch):
    monkeypatch.setattr(
        admin_auth_config,
        "settings",
        dataclasses.replace(
            admin_auth_config.settings,
            web_origins=[],
            cookie_samesite="strict",
            cookie_secure=True,
            cookie_domain=None,
            idle_timeout=datetime.timedelta(minutes=30),
            max_age=datetime.timedelta(hours=12),
        ),
    )


@pytest.fixture
def app():
    test_app = FastAPI(exception_handlers=app_module.app.exception_handlers)
    test_app.include_router(routes.router, prefix="/v1")
    return test_app


@pytest.fixture
def client(app):
    # https, or the Secure cookie isn't sent back.
    return TestClient(app, base_url="https://testserver")


@pytest.fixture
def admin_password():
    with db.get_session() as session:
        _, password = admin_users.create_admin(session, ADMIN_EMAIL)
    return password


def basic_auth(email: str, password: str) -> dict[str, str]:
    token = base64.b64encode(f"{email}:{password}".encode()).decode()
    return {"Authorization": f"Basic {token}"}


def login(client: TestClient, password: str, email: str = ADMIN_EMAIL):
    return client.post("/v1/auth/login", json={"email": email, "password": password})
