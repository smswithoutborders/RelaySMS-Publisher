# SPDX-License-Identifier: GPL-3.0-only

from unittest.mock import ANY, MagicMock

import pytest

from publisher import publications
from publisher.publications import (
    OfflineTagInvalidError,
    OfflineTagMissingError,
    ProtocolNotAllowedError,
)


def _payload(t_id=None):
    payload = MagicMock()
    payload.get_t_id.return_value = t_id
    payload.get_kid.return_value = 1
    payload.get_len_att.return_value = 0
    payload.get_content.return_value = b"ciphertext"
    return payload


def _dispatch(payload, **kwargs):
    return publications._dispatch(MagicMock(), MagicMock(), payload, **kwargs)


@pytest.fixture
def offline(monkeypatch):
    publish_offline = MagicMock(return_value="rmail")
    monkeypatch.setattr(publications, "_publish_offline_content", publish_offline)
    return publish_offline


@pytest.fixture(autouse=True)
def _reset_config(set_config):
    set_config(publications, "offline_config", allowed_protocols=[], shared_secret=None)


def test_https_offline_rejects_wrong_tag(set_config, offline):
    set_config(publications, "offline_config", shared_secret="s3cret")

    with pytest.raises(OfflineTagInvalidError):
        _dispatch(_payload(), protocol="https", tag="wrong")


@pytest.mark.parametrize("tag", [None, ""])
def test_https_offline_rejects_missing_tag(set_config, offline, tag):
    set_config(publications, "offline_config", shared_secret="s3cret")

    with pytest.raises(OfflineTagMissingError):
        _dispatch(_payload(), protocol="https", tag=tag)


def test_https_offline_succeeds_with_correct_tag(set_config, offline):
    set_config(publications, "offline_config", shared_secret="s3cret")

    result = _dispatch(_payload(), protocol="https", tag="s3cret")

    assert result == "rmail"
    offline.assert_called_once()


@pytest.mark.parametrize("protocol", ["smtp", "sms"])
def test_non_https_offline_ignores_tag_check(set_config, offline, protocol):
    set_config(publications, "offline_config", shared_secret="s3cret")

    result = _dispatch(_payload(), protocol=protocol, tag=None)

    assert result == "rmail"
    offline.assert_called_once()


def test_https_offline_unchecked_when_secret_unset(offline):
    result = _dispatch(_payload(), protocol="https", tag=None)

    assert result == "rmail"


def test_protocol_allowlist_is_still_enforced_before_tag_check(set_config, offline):
    set_config(
        publications,
        "offline_config",
        allowed_protocols=["smtp"],
        shared_secret="s3cret",
    )

    with pytest.raises(ProtocolNotAllowedError):
        _dispatch(_payload(), protocol="https", tag="s3cret")


def test_online_payload_bypasses_protocol_and_tag_checks(
    set_config, monkeypatch, offline
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
    publish_online = MagicMock(return_value="gmail")
    monkeypatch.setattr(publications, "_publish_online_content", publish_online)

    result = _dispatch(_payload(t_id=42), protocol="https", tag=None)

    assert result == "gmail"
    publish_online.assert_called_once_with(
        ANY, ANY, token_id=42, key_id=1, len_att=0, content_ciphertext=b"ciphertext"
    )
