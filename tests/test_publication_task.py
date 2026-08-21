# SPDX-License-Identifier: GPL-3.0-only

from contextlib import contextmanager
from unittest.mock import MagicMock

import pytest

import tasks.publication_task as publication_task
from publications import (
    AdapterIntegrationError,
    OfflineTagInvalidError,
    OfflineTagMissingError,
    PayloadMalformedError,
    PayloadNotSupportedError,
    ProtocolNotAllowedError,
)


@contextmanager
def _fake_session():
    yield MagicMock()


@pytest.fixture(autouse=True)
def _patch_infra(monkeypatch):
    monkeypatch.setattr(publication_task, "get_session", _fake_session)
    monkeypatch.setattr(publication_task, "_get_adapter_manager", lambda: MagicMock())
    monkeypatch.setattr(publication_task, "record_publication", MagicMock())


def _stub_service(monkeypatch, *, publish_return=None, publish_side_effect=None):
    fake_service = MagicMock()
    if publish_side_effect is not None:
        fake_service.publish.side_effect = publish_side_effect
    else:
        fake_service.publish.return_value = publish_return

    fake_cls = MagicMock()
    fake_cls.validate.return_value = (b"raw", b"seg", object())
    fake_cls.return_value = fake_service
    monkeypatch.setattr(publication_task, "PublicationService", fake_cls)
    return fake_service


def _run_with_publish_error(monkeypatch, error):
    fake_service = _stub_service(monkeypatch, publish_side_effect=error)
    publication_task.publish_message("text", "+12025550123", "https")
    return fake_service


@pytest.mark.parametrize(
    "error",
    [
        PayloadNotSupportedError("unsupported type"),
        PayloadMalformedError("bad payload"),
        ProtocolNotAllowedError("protocol not allowed"),
        OfflineTagMissingError("missing tag"),
        OfflineTagInvalidError("invalid tag"),
    ],
)
def test_pipeline_errors_are_caught_and_logged(monkeypatch, caplog, error):
    """The task must swallow these, not raise; the REST caller already got its 200."""
    fake_service = _run_with_publish_error(monkeypatch, error)

    fake_service.publish.assert_called_once()
    assert "Failed to process payload" in caplog.text
    publication_task.record_publication.assert_called_once()
    assert publication_task.record_publication.call_args.kwargs["status"] == "failed"


def test_adapter_integration_error_is_caught_and_logged(monkeypatch, caplog):
    fake_service = _run_with_publish_error(monkeypatch, AdapterIntegrationError("boom"))

    fake_service.publish.assert_called_once()
    assert "Failed to publish message" in caplog.text
    publication_task.record_publication.assert_called_once()
    assert publication_task.record_publication.call_args.kwargs["status"] == "failed"


def test_unexpected_error_is_caught_logged_and_recorded(monkeypatch, caplog):
    """A bare, unanticipated exception must not crash the worker."""
    fake_service = _run_with_publish_error(monkeypatch, RuntimeError("boom"))

    fake_service.publish.assert_called_once()
    assert "unexpected error" in caplog.text.lower()
    publication_task.record_publication.assert_called_once()
    kwargs = publication_task.record_publication.call_args.kwargs
    assert kwargs["status"] == "failed"
    assert kwargs["failure_reason"] == "unexpected_error"


def test_success_records_published_stat(monkeypatch):
    fake_service = _stub_service(monkeypatch, publish_return="gmail")

    publication_task.publish_message("text", "+12025550123", "https")

    fake_service.publish.assert_called_once()
    publication_task.record_publication.assert_called_once()
    kwargs = publication_task.record_publication.call_args.kwargs
    assert kwargs["status"] == "published"
    assert kwargs["platform_name"] == "gmail"


def test_incomplete_segment_session_skips_recording(monkeypatch):
    """service.publish() returns None while awaiting more segments; the task
    must return early without recording any outcome."""
    _stub_service(monkeypatch, publish_return=None)

    publication_task.publish_message("text", "+12025550123", "smtp")

    publication_task.record_publication.assert_not_called()


def test_tag_is_forwarded_to_service_publish(monkeypatch):
    fake_service = _stub_service(monkeypatch, publish_return="rmail")

    publication_task.publish_message("text", "+12025550123", "https", "s3cret-tag")

    assert fake_service.publish.call_args.kwargs["tag"] == "s3cret-tag"
