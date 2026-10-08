# SPDX-License-Identifier: GPL-3.0-only

import base64
import hashlib
from types import SimpleNamespace
from unittest.mock import ANY, MagicMock

import pytest
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey
from sqlalchemy import select

from lib_relaysms_payload_specs.generated import relaysms_spec_payload as rrs
from publisher import keys, publications
from publisher.db import get_session
from publisher.models.server_ephemeral_key import ServerEphemeralKey
from publisher.models.server_identity_key import get_private_key
from publisher.models.token import Token
from publisher.models.token import create as create_token
from publisher.platforms import ipc
from publisher.publications import (
    AdapterIntegrationError,
    OfflineTagInvalidError,
    OfflineTagMissingError,
    PayloadMalformedError,
    ProtocolNotAllowedError,
)
from tests.helpers import add_adapter

SENDER_HASH = "5447c1f50558292bd9df723f9fdc0b06b892199c7dcfaad5164f2d94dfd3470a"


def _payload(t_id=None):
    payload = MagicMock()
    payload.get_t_id.return_value = t_id
    payload.get_kid.return_value = 1
    payload.get_len_att.return_value = 0
    payload.get_content.return_value = b"ciphertext"
    return payload


def _dispatch(payload, **kwargs):
    return publications._dispatch(MagicMock(), payload, **kwargs)


@pytest.fixture
def offline(monkeypatch):
    publish_offline = MagicMock(return_value="rmail")
    monkeypatch.setattr(publications, "_publish_offline_content", publish_offline)
    return publish_offline


@pytest.fixture(autouse=True)
def _reset_config(set_config):
    set_config(publications, "offline_config", allowed_protocols=[], shared_secret=None)


def test_sender_id_is_a_stable_keyed_hash():
    sender_id = publications.pseudonymize_sender("+237123456789")

    assert sender_id == publications.pseudonymize_sender("+237123456789")
    assert sender_id != publications.pseudonymize_sender("+237123456780")
    assert sender_id != hashlib.sha256(b"+237123456789").hexdigest()


@pytest.mark.parametrize(
    ("address", "dialing_code", "country"),
    [
        ("+237123456789", None, "CM"),
        (SENDER_HASH, "237", "CM"),
        (SENDER_HASH, "44", "GB"),
        (SENDER_HASH, "999", None),
        (SENDER_HASH, None, None),
    ],
)
def test_country_comes_from_dialing_code_or_number(address, dialing_code, country):
    assert publications.sender_country(address, dialing_code) == country


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
        ANY, token_id=42, key_id=1, len_att=0, content_ciphertext=b"ciphertext"
    )


# Publishing end to end: real keys and ciphertext; only the adapter process is faked.

SENDER = "+237600000000"
# A 1x1 PNG, padded so the payload spans several SMS segments.
PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg=="
) + bytes(600)


@pytest.fixture
def adapter(monkeypatch, test_db):
    """Records adapter calls and answers each with `response`."""
    add_adapter("gmail", proto_id=0)
    add_adapter("rmail", proto_id=1)
    fake = SimpleNamespace(calls=[], response={"result": {"success": True}})

    def invoke(adapter_path, venv_path, method, params=None):
        fake.calls.append((adapter_path, method, params))
        return fake.response

    monkeypatch.setattr(ipc, "invoke", invoke)
    return fake


@pytest.fixture
def account(test_db):
    """A linked Gmail account with its key pools, as after an OAuth2 exchange."""
    client_keys = [X25519PrivateKey.generate() for _ in range(256)]
    public_keys = [
        SimpleNamespace(key_id=i, public_key=k.public_key().public_bytes_raw())
        for i, k in enumerate(client_keys)
    ]
    with get_session() as s:
        keys.initialize_server_identity_keys(s)
        token = create_token(
            s,
            platform="gmail",
            cat_id=0,
            proto_id=0,
            token_data={
                "account_id": "user@example.org",
                "token": {"access_token": "a1", "refresh_token": "r1"},
            },
        )
        _, token_slot, server_keys = keys.create_token_pools_and_encrypt(
            s, token.id, public_keys
        )
        return SimpleNamespace(
            token_id=token.token_id,
            # The token's own slot is used up; any other in 16-255 is free.
            slot=17 if token_slot != 17 else 18,
            client_keys=client_keys,
            server_keys=server_keys,
        )


def _email(attachment=None):
    return rrs.V1ContentsContainer(
        cat_id=rrs.V1ContentCategories.EMAIL,
        body=b"Hello",
        to=b"friend@example.org",
        subject=b"Hi",
        attachment=attachment,
    ).serialize()


def _encrypt(account, slot, content):
    with get_session() as s:
        ss_kid_pk = get_private_key(s, slot).public_key().public_bytes_raw()
    return rrs.v1_platform_publisher_encrypt(
        ec_kid=account.client_keys[slot].private_bytes_raw(),
        ss_kid_pk=ss_kid_pk,
        es_kid_pk=account.server_keys[slot],
        key_id=slot,
        plaintext=content,
    )


def _sms(contents, *, slot, token_id=None, attachment=None, sess_id=None):
    """The SMS text(s) a phone sends for this payload."""
    payload = rrs.V1Payloads(
        contents=contents,
        k_id=slot,
        len_att=len(attachment) if attachment else 0,
        t_id=token_id,
        sess_id=sess_id,
    )
    if attachment:
        return [segment.decode() for segment in payload.split(rrs.Transports.SMS)]
    return [base64.b64encode(payload.serialize_without_attachment()).decode()]


def _publish(text, protocol="sms"):
    payload_raw, raw_segment, payload_type = publications.validate(text)
    with get_session() as s:
        return publications.publish(
            s,
            payload_raw=payload_raw,
            sender_id=SENDER,
            raw_segment=raw_segment,
            payload_type=payload_type,
            protocol=protocol,
        )


def _slot_is_unused(account, slot):
    with get_session() as s:
        token = s.scalar(select(Token).where(Token.token_id == account.token_id))
        return (
            s.scalar(
                select(ServerEphemeralKey).where(
                    ServerEphemeralKey.token_hash_id == token.token_hash.id,
                    ServerEphemeralKey.key_index == slot,
                )
            )
            is not None
        )


def _stored_token(account):
    with get_session() as s:
        token = s.scalar(select(Token).where(Token.token_id == account.token_id))
        return token.token_data, token.token_hash.last_used_at


@pytest.mark.parametrize("text", ["not base64!", base64.b64encode(b"\xff").decode()])
def test_validate_rejects_text_that_is_not_a_payload(text):
    with pytest.raises(PayloadMalformedError):
        publications.validate(text)


def test_publish_sends_the_decrypted_email_to_the_adapter(account, adapter):
    contents = _encrypt(account, account.slot, _email())
    [text] = _sms(contents, slot=account.slot, token_id=account.token_id)

    assert _publish(text) == "gmail"

    path, method, params = adapter.calls[-1]
    assert (path.split("/")[-1], method) == ("gmail-0", "send_message")
    assert params["to_email"] == "friend@example.org"
    assert params["subject"] == "Hi"
    assert params["message"] == "Hello"
    assert params["from_email"] == "user@example.org"
    assert params["token"] == {"access_token": "a1", "refresh_token": "r1"}
    assert not _slot_is_unused(account, account.slot)
    assert _stored_token(account)[1] is not None


def test_publish_rejects_a_tampered_payload(account, adapter):
    contents = bytearray(_encrypt(account, account.slot, _email()))
    contents[-1] ^= 1
    [text] = _sms(bytes(contents), slot=account.slot, token_id=account.token_id)

    with pytest.raises(PayloadMalformedError):
        _publish(text)
    assert adapter.calls == []


def test_publish_saves_a_refreshed_oauth_token(account, adapter):
    refreshed = {"access_token": "a2", "refresh_token": "r2"}
    adapter.response = {"result": {"success": True, "refreshed_token": refreshed}}
    contents = _encrypt(account, account.slot, _email())
    [text] = _sms(contents, slot=account.slot, token_id=account.token_id)

    _publish(text)

    assert _stored_token(account)[0]["token"] == refreshed


def test_adapter_failure_names_the_platform(account, adapter):
    adapter.response = {"result": {"success": False, "message": "quota exceeded"}}
    contents = _encrypt(account, account.slot, _email())
    [text] = _sms(contents, slot=account.slot, token_id=account.token_id)

    with pytest.raises(AdapterIntegrationError, match="quota exceeded") as error:
        _publish(text)
    assert error.value.platform_name == "gmail"


def test_attachment_is_published_once_all_segments_arrive(account, adapter):
    # Payloads with attachments use the reserved slots 0-15.
    contents = _encrypt(account, 5, _email(attachment=PNG))
    texts = _sms(contents, slot=5, token_id=account.token_id, attachment=PNG, sess_id=3)
    assert len(texts) > 1

    results = [_publish(text) for text in reversed(texts)]

    assert results == [None] * (len(texts) - 1) + ["gmail"]
    [(_, _, params)] = adapter.calls
    [attached] = params["attachments"]
    assert attached["mimetype"] == "image/png"
    assert base64.b64decode(attached["data"]) == PNG


def test_offline_payload_goes_to_the_offline_adapter(test_db, adapter):
    with get_session() as s:
        keys.initialize_server_identity_keys(s)
        ss_pk = get_private_key(s, 3).public_key().public_bytes_raw()
    contents = rrs.OfflineFirst.encrypt(
        ss_pk=ss_pk,
        ec=X25519PrivateKey.generate().private_bytes_raw(),
        sc=X25519PrivateKey.generate().private_bytes_raw(),
        payload=_email(),
    ).serialize()
    [text] = _sms(contents, slot=3)

    assert _publish(text, protocol="smtp") == "rmail"

    path, method, params = adapter.calls[-1]
    assert (path.split("/")[-1], method) == ("rmail-1", "send_message")
    assert params["to_email"] == "friend@example.org"
    assert params["message"] == "Hello"
