# SPDX-License-Identifier: GPL-3.0-only

from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from twilio.request_validator import RequestValidator

import rest_services.v1.routes as routes
from publications import PayloadMalformedError

AUTH_TOKEN = "test-auth-token"
WEBHOOK_URL = "http://testserver/v1/twilio-sms"


@pytest.fixture
def client():
    app = FastAPI()
    app.include_router(routes.router, prefix="/v1")
    return TestClient(app)


@pytest.fixture(autouse=True)
def _enabled(monkeypatch):
    monkeypatch.setattr(routes, "TWILIO_SMS_TRANSPORT_ENABLED", True)
    monkeypatch.setattr(routes, "TWILIO_AUTH_TOKEN", AUTH_TOKEN)
    monkeypatch.setattr(routes, "publish_message", MagicMock())
    monkeypatch.setattr(routes, "forward_twilio_webhook", MagicMock())
    monkeypatch.setattr(
        routes.PublicationService, "validate", staticmethod(lambda text: None)
    )


def _signed_post(client, params, auth_token=AUTH_TOKEN, url=WEBHOOK_URL):
    signature = RequestValidator(auth_token).compute_signature(url, params)
    return client.post(
        "/v1/twilio-sms", data=params, headers={"X-Twilio-Signature": signature}
    )


def test_valid_signature_queues_publication(client):
    params = {"From": "+237123456789", "Body": "cGF5bG9hZA=="}
    response = _signed_post(client, params)

    assert response.status_code == 200
    assert "text/xml" in response.headers["content-type"]
    routes.publish_message.delay.assert_called_once_with(
        "cGF5bG9hZA==", "+237123456789", "sms"
    )


def test_invalid_signature_rejected(client):
    params = {"From": "+237123456789", "Body": "cGF5bG9hZA=="}
    response = _signed_post(client, params, auth_token="wrong-token")

    assert response.status_code == 403
    routes.publish_message.delay.assert_not_called()


def test_missing_signature_header_rejected(client):
    response = client.post(
        "/v1/twilio-sms", data={"From": "+237123456789", "Body": "cGF5bG9hZA=="}
    )

    assert response.status_code == 403
    routes.publish_message.delay.assert_not_called()


def test_missing_body_field_rejected(client):
    params = {"From": "+237123456789"}
    response = _signed_post(client, params)

    assert response.status_code == 400
    routes.publish_message.delay.assert_not_called()


def test_malformed_payload_rejected(client, monkeypatch):
    def _raise(text):
        raise PayloadMalformedError("bad payload")

    monkeypatch.setattr(routes.PublicationService, "validate", staticmethod(_raise))

    params = {"From": "+237123456789", "Body": "not-base64"}
    response = _signed_post(client, params)

    assert response.status_code == 400
    routes.publish_message.delay.assert_not_called()


def test_transport_disabled_returns_404(client, monkeypatch):
    monkeypatch.setattr(routes, "TWILIO_SMS_TRANSPORT_ENABLED", False)

    params = {"From": "+237123456789", "Body": "cGF5bG9hZA=="}
    response = _signed_post(client, params)

    assert response.status_code == 404
    routes.publish_message.delay.assert_not_called()


def test_forwarding_queued(client):
    params = {"From": "+237123456789", "Body": "cGF5bG9hZA=="}
    response = _signed_post(client, params)

    assert response.status_code == 200
    routes.forward_twilio_webhook.delay.assert_called_once_with(
        params, "+237123456789", "cGF5bG9hZA=="
    )
