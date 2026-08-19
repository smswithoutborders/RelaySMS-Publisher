# SPDX-License-Identifier: GPL-3.0-only

from unittest.mock import MagicMock

import pytest
import requests

import tasks.forward_task as forward_task

SAMPLE_PARAMS = {"From": "+237123456789", "Body": "cGF5bG9hZA=="}


@pytest.fixture(autouse=True)
def _no_urls(monkeypatch):
    monkeypatch.setattr(forward_task, "TWILIO_FORWARD_URLS_RAW", [])
    monkeypatch.setattr(forward_task, "TWILIO_FORWARD_URLS_JSON", [])


def test_noop_when_no_urls_configured(monkeypatch):
    mock_post = MagicMock()
    monkeypatch.setattr(forward_task._session, "post", mock_post)

    forward_task.forward_twilio_webhook(SAMPLE_PARAMS, "+237123456789", "cGF5bG9hZA==")

    mock_post.assert_not_called()


def test_forwards_raw_and_json_to_their_respective_urls(monkeypatch):
    monkeypatch.setattr(
        forward_task, "TWILIO_FORWARD_URLS_RAW", ["https://raw.example.com/hook"]
    )
    monkeypatch.setattr(
        forward_task, "TWILIO_FORWARD_URLS_JSON", ["https://json.example.com/hook"]
    )
    mock_post = MagicMock()
    monkeypatch.setattr(forward_task._session, "post", mock_post)

    params = {"From": "+237123456789", "Body": "cGF5bG9hZA==", "MessageSid": "SM123"}
    forward_task.forward_twilio_webhook(params, "+237123456789", "cGF5bG9hZA==")

    assert mock_post.call_count == 2
    calls_by_url = {call.args[0]: call.kwargs for call in mock_post.call_args_list}

    raw_kwargs = calls_by_url["https://raw.example.com/hook"]
    assert raw_kwargs["data"] == params
    assert raw_kwargs["timeout"] == forward_task.TWILIO_FORWARD_TIMEOUT

    json_kwargs = calls_by_url["https://json.example.com/hook"]
    assert json_kwargs["json"]["sender"] == "+237123456789"
    assert json_kwargs["json"]["text"] == "cGF5bG9hZA=="
    assert "received_at" in json_kwargs["json"]


def test_one_failing_destination_does_not_prevent_others(monkeypatch):
    monkeypatch.setattr(
        forward_task,
        "TWILIO_FORWARD_URLS_RAW",
        ["https://down.example.com/hook", "https://up.example.com/hook"],
    )

    def _fake_post(url, **kwargs):
        if "down" in url:
            raise requests.RequestException("connection refused")
        return MagicMock()

    mock_post = MagicMock(side_effect=_fake_post)
    monkeypatch.setattr(forward_task._session, "post", mock_post)

    forward_task.forward_twilio_webhook(SAMPLE_PARAMS, "+237123456789", "cGF5bG9hZA==")

    assert mock_post.call_count == 2
