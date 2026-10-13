# SPDX-License-Identifier: GPL-3.0-only

from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from publisher.api.rest.v1 import publications as publications_routes
from publisher.api.rest.v1 import routes
from publisher.publications import pseudonymize_sender
from publisher.publications import validate as real_validate
from publisher.tasks import publication_task

SENDER_HASH = "5447c1f50558292bd9df723f9fdc0b06b892199c7dcfaad5164f2d94dfd3470a"


@pytest.fixture
def client():
    app = FastAPI()
    app.include_router(routes.router, prefix="/v1")
    return TestClient(app)


@pytest.fixture(autouse=True)
def _stub_publish(monkeypatch):
    monkeypatch.setattr(publication_task.publish_message, "delay", MagicMock())
    monkeypatch.setattr(
        publications_routes.publications,
        "validate",
        lambda text: None,
    )


@pytest.mark.parametrize(
    ("sender", "country"),
    [
        ({"address": SENDER_HASH, "dialing_code": "237"}, "CM"),
        ({"address": "+12025550123"}, "US"),
    ],
)
def test_valid_payload_queues_publication_under_hashed_sender(client, sender, country):
    response = client.post("/v1/publications", json={**sender, "text": "cGF5bG9hZA=="})

    assert response.status_code == 200
    publication_task.publish_message.delay.assert_called_once_with(
        "cGF5bG9hZA==", pseudonymize_sender(sender["address"]), "https", None, country
    )


def test_invalid_dialing_code_rejected(client):
    response = client.post(
        "/v1/publications",
        json={"address": SENDER_HASH, "dialing_code": "abc", "text": "cGF5bG9hZA=="},
    )

    assert response.status_code == 422
    publication_task.publish_message.delay.assert_not_called()


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
    publication_task.publish_message.delay.assert_called_once_with(
        "cGF5bG9hZA==", pseudonymize_sender("+12025550123"), "https", "s3cret-tag", "US"
    )


def test_malformed_payload_rejected(client, monkeypatch):
    monkeypatch.setattr(publications_routes.publications, "validate", real_validate)

    response = client.post(
        "/v1/publications",
        json={"address": "+12025550123", "text": "not-base64"},
    )

    assert response.status_code == 400
    publication_task.publish_message.delay.assert_not_called()
