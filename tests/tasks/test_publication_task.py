# SPDX-License-Identifier: GPL-3.0-only

from contextlib import contextmanager
from unittest.mock import MagicMock

import pytest

from publisher.keys import KeyNotFoundError, KeyUnavailableError, TokenVerificationError
from publisher.publications import (
    AdapterIntegrationError,
    OfflineTagInvalidError,
    OfflineTagMissingError,
    PayloadMalformedError,
    PayloadNotSupportedError,
    ProtocolNotAllowedError,
)
from publisher.tasks import publication_task
from relaysms_adapter_sdk.errors import RateLimitedError, UpstreamError

EVENTS = []


@contextmanager
def _fake_session():
    EVENTS.append("open")
    try:
        yield MagicMock()
    except Exception:
        EVENTS.append("rollback")
        raise
    EVENTS.append("commit")


@pytest.fixture(autouse=True)
def _patch_infra(monkeypatch):
    EVENTS.clear()
    monkeypatch.setattr(publication_task, "get_session", _fake_session)
    monkeypatch.setattr(publication_task, "record_publication", MagicMock())


def _stub_publications(monkeypatch, *, prepare_error=None, send_error=None):
    """Stub each publication step, making prepare or send raise the given error."""
    stub = MagicMock()
    stub.validate.return_value = (b"raw", b"seg", object())
    stub.prepare.return_value = MagicMock(platform="gmail")
    stub.prepare.side_effect = prepare_error

    def send(delivery):
        EVENTS.append("send")
        if send_error:
            raise send_error

    stub.send.side_effect = send
    for name in ("validate", "prepare", "send", "finish", "store_token"):
        monkeypatch.setattr(publication_task.publications, name, getattr(stub, name))
    return stub


def _run_with_publish_error(monkeypatch, error):
    stub = _stub_publications(monkeypatch, prepare_error=error)
    publication_task.publish_message("text", "sender", "https")
    return stub


@pytest.mark.parametrize(
    "error, reason",
    [
        (PayloadNotSupportedError("unsupported type"), "payload_not_supported"),
        (PayloadMalformedError("bad payload"), "payload_malformed"),
        (KeyNotFoundError("Token not found"), "token_not_found"),
        (KeyUnavailableError("key used"), "key_unavailable"),
        (TokenVerificationError("unknown key"), "token_verification_failed"),
    ],
)
def test_pipeline_errors_are_recorded_as_failed(monkeypatch, caplog, error, reason):
    _run_with_publish_error(monkeypatch, error)

    assert "Failed to process payload" in caplog.text
    publication_task.record_publication.assert_called_once()
    kwargs = publication_task.record_publication.call_args.kwargs
    assert kwargs["status"] == "failed"
    assert kwargs["failure_reason"] == reason


@pytest.mark.parametrize(
    "error, reason",
    [
        (ProtocolNotAllowedError("protocol not allowed"), "protocol_not_allowed"),
        (OfflineTagMissingError("missing tag"), "offline_tag_missing"),
        (OfflineTagInvalidError("invalid tag"), "offline_tag_invalid"),
    ],
)
def test_offline_refusals_are_rejected_not_failed(monkeypatch, caplog, error, reason):
    _run_with_publish_error(monkeypatch, error)

    assert "Rejected payload" in caplog.text
    kwargs = publication_task.record_publication.call_args.kwargs
    assert (kwargs["status"], kwargs["failure_reason"]) == ("rejected", reason)


def test_a_subclass_of_a_mapped_error_keeps_its_code(monkeypatch):
    class TruncatedPayloadError(PayloadMalformedError):
        pass

    _run_with_publish_error(monkeypatch, TruncatedPayloadError("short"))

    kwargs = publication_task.record_publication.call_args.kwargs
    assert kwargs["failure_reason"] == "payload_malformed"


@pytest.mark.parametrize(
    "code, reason",
    [
        (RateLimitedError.code, "adapter_rate_limited"),
        (-32099, "adapter_error"),
    ],
)
def test_adapter_failures_record_a_code_not_the_message(monkeypatch, code, reason):
    error = AdapterIntegrationError("Google returned 400: to=a@b.c", code=code)
    _stub_publications(monkeypatch, send_error=error)

    publication_task.publish_message("text", "sender", "https")

    kwargs = publication_task.record_publication.call_args.kwargs
    assert kwargs["failure_reason"] == reason


def test_a_failed_send_keeps_the_refreshed_token(monkeypatch, caplog):
    error = AdapterIntegrationError("boom", code=UpstreamError.code, token={"t": 2})
    stub = _stub_publications(monkeypatch, send_error=error)

    publication_task.publish_message("text", "sender", "https")

    assert "Failed to publish message" in caplog.text
    assert stub.store_token.call_args.args[2] == {"t": 2}
    stub.finish.assert_not_called()
    publication_task.record_publication.assert_called_once()
    assert publication_task.record_publication.call_args.kwargs["status"] == "failed"


def test_unexpected_error_is_caught_logged_and_recorded(monkeypatch, caplog):
    _run_with_publish_error(monkeypatch, RuntimeError("boom"))

    assert "unexpected error" in caplog.text.lower()
    publication_task.record_publication.assert_called_once()
    kwargs = publication_task.record_publication.call_args.kwargs
    assert kwargs["status"] == "failed"
    assert kwargs["failure_reason"] == "unexpected_error"


def test_success_records_published_stat(monkeypatch):
    stub = _stub_publications(monkeypatch)

    publication_task.publish_message("text", "sender", "https", country_code="CM")

    assert stub.prepare.call_args.kwargs["sender_id"] == "sender"
    assert EVENTS == ["open", "commit", "send", "open", "commit"]
    stub.finish.assert_called_once()
    publication_task.record_publication.assert_called_once()
    kwargs = publication_task.record_publication.call_args.kwargs
    assert kwargs["status"] == "published"
    assert kwargs["platform_name"] == "gmail"
    assert kwargs["country_code"] == "CM"


def test_incomplete_segment_session_skips_recording(monkeypatch):
    stub = _stub_publications(monkeypatch)
    stub.prepare.return_value = None

    publication_task.publish_message("text", "sender", "smtp")

    stub.send.assert_not_called()
    publication_task.record_publication.assert_not_called()


def test_a_recording_failure_after_the_send_is_not_a_failed_publication(
    monkeypatch, caplog
):
    stub = _stub_publications(monkeypatch)
    stub.finish.side_effect = RuntimeError("db dropped")

    publication_task.publish_message("text", "sender", "https")

    assert EVENTS == ["open", "commit", "send", "open", "rollback"]
    assert "couldn't record the result" in caplog.text
    publication_task.record_publication.assert_not_called()


def test_a_failed_payload_rolls_back_before_sending(monkeypatch):
    _run_with_publish_error(monkeypatch, PayloadMalformedError("bad payload"))

    assert EVENTS == ["open", "rollback", "open", "commit"]


def test_tag_is_passed_to_prepare(monkeypatch):
    stub = _stub_publications(monkeypatch)

    publication_task.publish_message("text", "sender", "https", "s3cret-tag")

    assert stub.prepare.call_args.kwargs["tag"] == "s3cret-tag"
