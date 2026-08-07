# SPDX-License-Identifier: GPL-3.0-only

from contextlib import contextmanager
from unittest.mock import MagicMock

import pytest

import tasks.publication_task as publication_task
from publications import (
    AdapterIntegrationError,
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


def _run_with_publish_error(monkeypatch, error):
    fake_service = MagicMock()
    fake_service.publish.side_effect = error

    fake_cls = MagicMock()
    fake_cls.validate.return_value = (b"raw", b"seg", object())
    fake_cls.return_value = fake_service
    monkeypatch.setattr(publication_task, "PublicationService", fake_cls)

    publication_task.publish_message("text", "+12025550123", "https")
    return fake_service


@pytest.mark.parametrize(
    "error",
    [
        PayloadNotSupportedError("unsupported type"),
        PayloadMalformedError("bad payload"),
        ProtocolNotAllowedError("protocol not allowed"),
    ],
)
def test_pipeline_errors_are_caught_and_logged(monkeypatch, caplog, error):
    """The task must swallow these, not raise; the REST caller already got its 200."""
    fake_service = _run_with_publish_error(monkeypatch, error)

    fake_service.publish.assert_called_once()
    assert "Failed to process payload" in caplog.text


def test_adapter_integration_error_is_caught_and_logged(monkeypatch, caplog):
    fake_service = _run_with_publish_error(monkeypatch, AdapterIntegrationError("boom"))

    fake_service.publish.assert_called_once()
    assert "Failed to publish message" in caplog.text
