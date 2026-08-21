# SPDX-License-Identifier: GPL-3.0-only

from unittest.mock import MagicMock

import pytest

import publications
from publications import (
    OfflineTagInvalidError,
    OfflineTagMissingError,
    ProtocolNotAllowedError,
    PublicationService,
)


def _set_shared_secret(monkeypatch, secret):
    monkeypatch.setattr(publications, "OFFLINE_PUBLISH_SHARED_SECRET", secret)


def _payload(t_id=None):
    payload = MagicMock()
    payload.get_t_id.return_value = t_id
    payload.get_kid.return_value = 1
    payload.get_len_att.return_value = 0
    payload.get_content.return_value = b"ciphertext"
    return payload


@pytest.fixture
def service(monkeypatch):
    svc = PublicationService(session=MagicMock(), adapter_manager=MagicMock())
    monkeypatch.setattr(
        svc, "_publish_offline_content", MagicMock(return_value="rmail")
    )
    return svc


@pytest.fixture(autouse=True)
def _reset_config(monkeypatch):
    monkeypatch.setattr(publications, "OFFLINE_PUBLISH_ALLOWED_PROTOCOLS", [])
    _set_shared_secret(monkeypatch, None)


def test_https_offline_rejects_wrong_tag(monkeypatch, service):
    _set_shared_secret(monkeypatch, "s3cret")

    with pytest.raises(OfflineTagInvalidError):
        service._dispatch(_payload(), protocol="https", tag="wrong")


@pytest.mark.parametrize("tag", [None, ""])
def test_https_offline_rejects_missing_tag(monkeypatch, service, tag):
    _set_shared_secret(monkeypatch, "s3cret")

    with pytest.raises(OfflineTagMissingError):
        service._dispatch(_payload(), protocol="https", tag=tag)


def test_https_offline_succeeds_with_correct_tag(monkeypatch, service):
    _set_shared_secret(monkeypatch, "s3cret")

    result = service._dispatch(_payload(), protocol="https", tag="s3cret")

    assert result == "rmail"
    service._publish_offline_content.assert_called_once()


@pytest.mark.parametrize("protocol", ["smtp", "sms"])
def test_non_https_offline_ignores_tag_check(monkeypatch, service, protocol):
    _set_shared_secret(monkeypatch, "s3cret")

    result = service._dispatch(_payload(), protocol=protocol, tag=None)

    assert result == "rmail"
    service._publish_offline_content.assert_called_once()


def test_https_offline_unchecked_when_secret_unset(service):
    result = service._dispatch(_payload(), protocol="https", tag=None)

    assert result == "rmail"


def test_protocol_allowlist_is_still_enforced_before_tag_check(monkeypatch, service):
    monkeypatch.setattr(publications, "OFFLINE_PUBLISH_ALLOWED_PROTOCOLS", ["smtp"])
    _set_shared_secret(monkeypatch, "s3cret")

    with pytest.raises(ProtocolNotAllowedError):
        service._dispatch(_payload(), protocol="https", tag="s3cret")


def test_online_payload_bypasses_protocol_and_tag_checks(monkeypatch, service):
    """A token-based (online) payload must skip the offline-only allowlist/tag
    checks entirely, even over https with a secret configured and no tag."""
    monkeypatch.setattr(publications, "OFFLINE_PUBLISH_ALLOWED_PROTOCOLS", ["smtp"])
    _set_shared_secret(monkeypatch, "s3cret")
    monkeypatch.setattr(
        service, "_publish_online_content", MagicMock(return_value="gmail")
    )

    result = service._dispatch(_payload(t_id=42), protocol="https", tag=None)

    assert result == "gmail"
    service._publish_online_content.assert_called_once_with(
        token_id=42, key_id=1, len_att=0, content_ciphertext=b"ciphertext"
    )
