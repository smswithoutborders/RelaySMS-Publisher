# SPDX-License-Identifier: GPL-3.0-only

import json
from unittest.mock import MagicMock

import pytest
from imap_tools import MailMessage

import smtp_listener
from publications import PayloadMalformedError

_next_uid = iter(range(1, 10000))


def build_email(body: str, from_addr: str = "user@example.com") -> MailMessage:
    """Build an imap_tools MailMessage (with a UID, as a real IMAP fetch
    would produce) from raw RFC822 bytes, without needing a real IMAP
    connection."""
    headers = []
    if from_addr is not None:
        headers.append(f"From: {from_addr}")
    headers.append("To: relay@publisher.example")
    headers.append("Subject: test")
    headers.append("Content-Type: text/plain; charset=utf-8")
    raw = ("\r\n".join(headers) + "\r\n\r\n" + body + "\r\n").encode()
    uid = next(_next_uid)
    return MailMessage([(f"1 (UID {uid} RFC822 {{{len(raw)}}}".encode(), raw)])


@pytest.fixture(autouse=True)
def _default_auth_allow(monkeypatch):
    """By default, allow through the sender/auth checks so each test only
    has to override what it's actually exercising."""
    monkeypatch.setattr(smtp_listener.smtp_auth, "is_sender_allowed", lambda addr: True)
    monkeypatch.setattr(
        smtp_listener.smtp_auth, "evaluate", lambda msg, raw, addr: (True, "ok")
    )
    monkeypatch.setattr(smtp_listener.publish_message, "delay", MagicMock())
    monkeypatch.setattr(
        smtp_listener.PublicationService, "validate", staticmethod(lambda text: None)
    )
    yield


def test_discards_when_no_from():
    msg = build_email("{}", from_addr=None)
    assert smtp_listener.process_incoming_email(msg) is True
    smtp_listener.publish_message.delay.assert_not_called()


def test_discards_when_sender_not_allowed(monkeypatch):
    monkeypatch.setattr(
        smtp_listener.smtp_auth, "is_sender_allowed", lambda addr: False
    )
    msg = build_email(json.dumps({"address": "+1", "text": "dGVzdA=="}))
    assert smtp_listener.process_incoming_email(msg) is True
    smtp_listener.publish_message.delay.assert_not_called()


def test_discards_when_authentication_fails(monkeypatch):
    monkeypatch.setattr(
        smtp_listener.smtp_auth,
        "evaluate",
        lambda msg, raw, addr: (False, "DKIM verdict is not 'pass'"),
    )
    msg = build_email(json.dumps({"address": "+1", "text": "dGVzdA=="}))
    assert smtp_listener.process_incoming_email(msg) is True
    smtp_listener.publish_message.delay.assert_not_called()


def test_discards_on_invalid_json_body():
    msg = build_email("this is not json")
    assert smtp_listener.process_incoming_email(msg) is True
    smtp_listener.publish_message.delay.assert_not_called()


def test_discards_on_schema_validation_error():
    msg = build_email(json.dumps({"address": "+1"}))  # missing "text"
    assert smtp_listener.process_incoming_email(msg) is True
    smtp_listener.publish_message.delay.assert_not_called()


def test_discards_when_payload_validation_fails(monkeypatch):
    def _raise(_text):
        raise PayloadMalformedError("bad payload")

    monkeypatch.setattr(
        smtp_listener.PublicationService, "validate", staticmethod(_raise)
    )
    msg = build_email(json.dumps({"address": "+1", "text": "dGVzdA=="}))
    assert smtp_listener.process_incoming_email(msg) is True
    smtp_listener.publish_message.delay.assert_not_called()


def test_queues_on_success():
    msg = build_email(json.dumps({"address": "+12025550123", "text": "dGVzdA=="}))
    assert smtp_listener.process_incoming_email(msg) is True
    smtp_listener.publish_message.delay.assert_called_once_with(
        "dGVzdA==", "+12025550123", "smtp"
    )


def test_leaves_email_for_retry_on_unexpected_error(monkeypatch):
    def _raise(_addr):
        raise RuntimeError("boom")

    monkeypatch.setattr(smtp_listener.smtp_auth, "is_sender_allowed", _raise)
    msg = build_email(json.dumps({"address": "+1", "text": "dGVzdA=="}))
    assert smtp_listener.process_incoming_email(msg) is False
    smtp_listener.publish_message.delay.assert_not_called()
