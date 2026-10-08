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


@contextmanager
def _fake_session():
    yield MagicMock()


@pytest.fixture(autouse=True)
def _patch_infra(monkeypatch):
    monkeypatch.setattr(publication_task, "get_session", _fake_session)
    monkeypatch.setattr(publication_task, "record_publication", MagicMock())


def _stub_publications(monkeypatch, *, publish_return=None, publish_side_effect=None):
    stub = MagicMock()
    stub.validate.return_value = (b"raw", b"seg", object())
    if publish_side_effect is not None:
        stub.publish.side_effect = publish_side_effect
    else:
        stub.publish.return_value = publish_return

    monkeypatch.setattr(publication_task.publications, "validate", stub.validate)
    monkeypatch.setattr(publication_task.publications, "publish", stub.publish)
    return stub


def _run_with_publish_error(monkeypatch, error):
    stub = _stub_publications(monkeypatch, publish_side_effect=error)
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

    stub.publish.assert_called_once()
    assert "Failed to process payload" in caplog.text
    publication_task.record_publication.assert_called_once()
    kwargs = publication_task.record_publication.call_args.kwargs
    assert kwargs["status"] == "failed"
    assert kwargs["failure_reason"] == str(error)


def test_adapter_integration_error_is_caught_and_logged(monkeypatch, caplog):
    stub = _run_with_publish_error(monkeypatch, AdapterIntegrationError("boom"))

    stub.publish.assert_called_once()
    assert "Failed to publish message" in caplog.text
    publication_task.record_publication.assert_called_once()
    assert publication_task.record_publication.call_args.kwargs["status"] == "failed"


def test_unexpected_error_is_caught_logged_and_recorded(monkeypatch, caplog):
    """A bare, unanticipated exception must not crash the worker."""
    stub = _run_with_publish_error(monkeypatch, RuntimeError("boom"))

    stub.publish.assert_called_once()
    assert "unexpected error" in caplog.text.lower()
    publication_task.record_publication.assert_called_once()
    kwargs = publication_task.record_publication.call_args.kwargs
    assert kwargs["status"] == "failed"
    assert kwargs["failure_reason"] == "unexpected_error"


def test_success_records_published_stat(monkeypatch):
    stub = _stub_publications(monkeypatch, publish_return="gmail")

    publication_task.publish_message("text", "sender", "https", country_code="CM")

    stub.publish.assert_called_once()
    assert stub.publish.call_args.kwargs["sender_id"] == "sender"
    publication_task.record_publication.assert_called_once()
    kwargs = publication_task.record_publication.call_args.kwargs
    assert kwargs["status"] == "published"
    assert kwargs["platform_name"] == "gmail"
    assert kwargs["country_code"] == "CM"


def test_incomplete_segment_session_skips_recording(monkeypatch):
    """Return early without recording an outcome while awaiting more segments."""
    _stub_publications(monkeypatch, publish_return=None)

    publication_task.publish_message("text", "sender", "smtp")

    publication_task.record_publication.assert_not_called()


def test_tag_is_forwarded_to_service_publish(monkeypatch):
    stub = _stub_publications(monkeypatch, publish_return="rmail")

    publication_task.publish_message("text", "sender", "https", "s3cret-tag")

    assert stub.publish.call_args.kwargs["tag"] == "s3cret-tag"
