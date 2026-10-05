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
def _reset_config(set_config):
    set_config(publications, "offline_config", allowed_protocols=[], shared_secret=None)


def test_https_offline_rejects_wrong_tag(set_config, service):
    set_config(publications, "offline_config", shared_secret="s3cret")

    with pytest.raises(OfflineTagInvalidError):
        service._dispatch(_payload(), protocol="https", tag="wrong")


@pytest.mark.parametrize("tag", [None, ""])
def test_https_offline_rejects_missing_tag(set_config, service, tag):
    set_config(publications, "offline_config", shared_secret="s3cret")

    with pytest.raises(OfflineTagMissingError):
        service._dispatch(_payload(), protocol="https", tag=tag)


def test_https_offline_succeeds_with_correct_tag(set_config, service):
    set_config(publications, "offline_config", shared_secret="s3cret")

    result = service._dispatch(_payload(), protocol="https", tag="s3cret")

    assert result == "rmail"
    service._publish_offline_content.assert_called_once()


@pytest.mark.parametrize("protocol", ["smtp", "sms"])
def test_non_https_offline_ignores_tag_check(set_config, service, protocol):
    set_config(publications, "offline_config", shared_secret="s3cret")

    result = service._dispatch(_payload(), protocol=protocol, tag=None)

    assert result == "rmail"
    service._publish_offline_content.assert_called_once()


def test_https_offline_unchecked_when_secret_unset(service):
    result = service._dispatch(_payload(), protocol="https", tag=None)

    assert result == "rmail"


def test_protocol_allowlist_is_still_enforced_before_tag_check(set_config, service):
    set_config(
        publications,
        "offline_config",
        allowed_protocols=["smtp"],
        shared_secret="s3cret",
    )

    with pytest.raises(ProtocolNotAllowedError):
        service._dispatch(_payload(), protocol="https", tag="s3cret")


def test_online_payload_bypasses_protocol_and_tag_checks(
    set_config, monkeypatch, service
):
    """Skip the offline-only allowlist and tag checks for online payloads.

    Holds even over https with a secret configured and no tag.
    """
    set_config(
        publications,
        "offline_config",
        allowed_protocols=["smtp"],
        shared_secret="s3cret",
    )
    monkeypatch.setattr(
        service, "_publish_online_content", MagicMock(return_value="gmail")
    )

    result = service._dispatch(_payload(t_id=42), protocol="https", tag=None)

    assert result == "gmail"
    service._publish_online_content.assert_called_once_with(
        token_id=42, key_id=1, len_att=0, content_ciphertext=b"ciphertext"
    )
