# SPDX-License-Identifier: GPL-3.0-only

from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import rest_services.v1.routes as routes
from publications import PayloadMalformedError


@pytest.fixture
def client():
    app = FastAPI()
    app.include_router(routes.router, prefix="/v1")
    return TestClient(app)


@pytest.fixture(autouse=True)
def _stub_publish(monkeypatch):
    monkeypatch.setattr(routes, "publish_message", MagicMock())
    monkeypatch.setattr(
        routes.PublicationService, "validate", staticmethod(lambda text: None)
    )


def test_valid_payload_queues_publication(client):
    response = client.post(
        "/v1/publications",
        json={"address": "+12025550123", "text": "cGF5bG9hZA=="},
    )

    assert response.status_code == 200
    routes.publish_message.delay.assert_called_once_with(
        "cGF5bG9hZA==", "+12025550123", "https", None
    )


def test_tag_is_forwarded_when_present(client):
    response = client.post(
        "/v1/publications",
        json={
            "address": "+12025550123",
            "text": "cGF5bG9hZA==",
            "tag": "s3cret-tag",
        },
    )

    assert response.status_code == 200
    routes.publish_message.delay.assert_called_once_with(
        "cGF5bG9hZA==", "+12025550123", "https", "s3cret-tag"
    )


def test_malformed_payload_rejected(client, monkeypatch):
    def _raise(text):
        raise PayloadMalformedError("bad payload")

    monkeypatch.setattr(routes.PublicationService, "validate", staticmethod(_raise))

    response = client.post(
        "/v1/publications",
        json={"address": "+12025550123", "text": "not-base64"},
    )

    assert response.status_code == 400
    routes.publish_message.delay.assert_not_called()
