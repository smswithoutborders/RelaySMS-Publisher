# SPDX-License-Identifier: GPL-3.0-only

from contextlib import contextmanager
from unittest.mock import MagicMock

import pytest

from publisher.keys import TokenVerificationError
from publisher.publications import (
    AdapterIntegrationError,
    OfflineTagInvalidError,
    OfflineTagMissingError,
    PayloadMalformedError,
    PayloadNotSupportedError,
    ProtocolNotAllowedError,
)
from publisher.tasks import publication_task

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
    """Stub each publication step; an error makes that step raise it."""
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
    "error",
    [
        PayloadNotSupportedError("unsupported type"),
        PayloadMalformedError("bad payload"),
        ProtocolNotAllowedError("protocol not allowed"),
        OfflineTagMissingError("missing tag"),
        OfflineTagInvalidError("invalid tag"),
        TokenVerificationError("unknown key"),
    ],
)
def test_pipeline_errors_are_caught_and_logged(monkeypatch, caplog, error):
    """The task must swallow these, not raise; the REST caller already got its 200."""
    stub = _run_with_publish_error(monkeypatch, error)

    stub.send.assert_not_called()
    assert "Failed to process payload" in caplog.text
    publication_task.record_publication.assert_called_once()
    kwargs = publication_task.record_publication.call_args.kwargs
    assert kwargs["status"] == "failed"
    assert kwargs["failure_reason"] == str(error)


def test_a_failed_send_rolls_back_and_keeps_the_refreshed_token(monkeypatch, caplog):
    error = AdapterIntegrationError("boom", token={"t": 2})
    stub = _stub_publications(monkeypatch, send_error=error)

    publication_task.publish_message("text", "sender", "https")

    # The keys' deletion is rolled back; the failure is recorded afterwards.
    assert EVENTS == ["open", "send", "rollback", "open", "commit"]
    assert "Failed to publish message" in caplog.text
    assert stub.store_token.call_args.args[2] == {"t": 2}
    stub.finish.assert_not_called()
    publication_task.record_publication.assert_called_once()
    assert publication_task.record_publication.call_args.kwargs["status"] == "failed"


def test_unexpected_error_is_caught_logged_and_recorded(monkeypatch, caplog):
    """A bare, unanticipated exception must not crash the worker."""
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
    stub.finish.assert_called_once()
    publication_task.record_publication.assert_called_once()
    kwargs = publication_task.record_publication.call_args.kwargs
    assert kwargs["status"] == "published"
    assert kwargs["platform_name"] == "gmail"
    assert kwargs["country_code"] == "CM"


def test_incomplete_segment_session_skips_recording(monkeypatch):
    """Return early without recording an outcome while awaiting more segments."""
    stub = _stub_publications(monkeypatch)
    stub.prepare.return_value = None

    publication_task.publish_message("text", "sender", "smtp")

    stub.send.assert_not_called()
    publication_task.record_publication.assert_not_called()


def test_a_successful_send_commits_once(monkeypatch):
    _stub_publications(monkeypatch)

    publication_task.publish_message("text", "sender", "https")

    assert EVENTS == ["open", "send", "commit"]


def test_a_rejected_payload_rolls_back_before_sending(monkeypatch):
    _run_with_publish_error(monkeypatch, PayloadMalformedError("bad payload"))

    assert EVENTS == ["open", "rollback", "open", "commit"]


def test_tag_is_forwarded_to_service_publish(monkeypatch):
    stub = _stub_publications(monkeypatch)

    publication_task.publish_message("text", "sender", "https", "s3cret-tag")

    assert stub.prepare.call_args.kwargs["tag"] == "s3cret-tag"
