# SPDX-License-Identifier: GPL-3.0-only

import base64
import datetime
import hashlib
from concurrent import futures
from types import SimpleNamespace
from unittest.mock import MagicMock

import grpc
import pytest
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey
from sqlalchemy import func, select

import publisher.models  # noqa: F401  (registers every table on Base.metadata)
from lib_relaysms_payload_specs.generated import relaysms_spec_payload as rrs
from protos.v3 import publisher_pb2, publisher_pb2_grpc
from publisher import db, keys
from publisher.api.grpc.interceptors import V1AuthInterceptor
from publisher.api.grpc.server import V3_SERVICE, interceptors
from publisher.api.grpc.v3 import revoke_oauth2_token
from publisher.api.grpc.v3.servicer import PublisherServicerV3
from publisher.db import Base, get_session
from publisher.models.server_ephemeral_key import ServerEphemeralKey
from publisher.models.server_identity_key import get_public_key
from publisher.models.token import Token
from publisher.platforms import ipc
from relaysms_adapter_sdk import (
    AuthenticationError,
    InvalidParamsError,
    RateLimitedError,
    UpstreamError,
)
from tests.helpers import add_adapter
from tools import client_helpers

OAUTH2_EXCHANGE = {
    "identifier": "user@example.org",
    "token": {"access_token": "access-token"},
    "name": None,
}
PNBA_EXCHANGE = {
    "identifier": "+237600000000",
    "token": {"session_string": "session-data"},
    "name": None,
}


def _public_key(key_id):
    with get_session() as s:
        return base64.urlsafe_b64decode(get_public_key(s, key_id)["public_key"])


@pytest.fixture(autouse=True)
def server_keys(monkeypatch):
    db.dispose_engine()
    Base.metadata.create_all(db.get_engine())
    with get_session() as s:
        keys.initialize_server_identity_keys(s)
    add_adapter("gmail", proto_id=0, cat_id=1)
    add_adapter("telegram", proto_id=1, cat_id=2)
    # The client helpers fetch server public keys over REST; read them from the db.
    monkeypatch.setattr(
        client_helpers,
        "fetch_server_identity_public_key",
        lambda _url, key_id: _public_key(key_id),
    )
    yield
    db.dispose_engine()


@pytest.fixture
def adapter(adapter_calls):
    return adapter_calls


@pytest.fixture
def stub():
    service = PublisherServicerV3()
    server = grpc.server(
        futures.ThreadPoolExecutor(max_workers=4), interceptors=interceptors()
    )
    publisher_pb2_grpc.add_PublisherServicer_to_server(service, server)
    port = server.add_insecure_port("127.0.0.1:0")
    server.start()
    with grpc.insecure_channel(f"127.0.0.1:{port}") as channel:
        yield publisher_pb2_grpc.PublisherStub(channel)
    server.stop(None)


def signed_metadata(method, payload=None):
    _, _, metadata = client_helpers.build_v1_request_metadata(
        rest_api="", method_name=f"/publisher.v3.Publisher/{method}", payload=payload
    )
    return metadata


def call(stub, method, request, payload=None):
    return getattr(stub, method)(request, metadata=signed_metadata(method, payload))


def rpc_error(stub, method, request, payload=None, metadata=None):
    with pytest.raises(grpc.RpcError) as error:
        if metadata is None:
            metadata = signed_metadata(method, payload)
        getattr(stub, method)(request, metadata=metadata)
    return error.value


def client_keys():
    keypairs = [X25519PrivateKey.generate() for _ in range(256)]
    public_keys = [
        publisher_pb2.PublicKey(key_id=i, public_key=kp.public_key().public_bytes_raw())
        for i, kp in enumerate(keypairs)
    ]
    return keypairs, public_keys


def server_public_key(response, key_id):
    return next(
        k.public_key
        for k in response.server_ephemeral_public_keys
        if k.key_id == key_id
    )


def decrypt_token(response, keypairs):
    key_id = response.key_id
    return rrs.v1_token_decrypt_client(
        ec_kid=keypairs[key_id].private_bytes_raw(),
        ss_kid_pk=client_helpers.fetch_server_identity_public_key("", key_id),
        es_kid_pk=server_public_key(response, key_id),
        key_id=key_id,
        received_payload=response.token_ciphertext,
    )


def encrypt_token(response, keypairs, token, key_id=1):
    """Encrypt a token with a key pair the server still holds, as revoke does.

    Exchange puts the token in a slot from 16-255, so lower slots stay held.
    """
    ciphertext = rrs.v1_token_encrypt_client(
        ec_kid=keypairs[key_id].private_bytes_raw(),
        ss_kid_pk=client_helpers.fetch_server_identity_public_key("", key_id),
        es_kid_pk=server_public_key(response, key_id),
        key_id=key_id,
        token=token,
    )
    return ciphertext


def stored_token(token_id):
    """The stored token's data and hash, or None once it is deleted."""
    with get_session() as s:
        token = s.scalar(select(Token).where(Token.token_id == token_id))
        if token is None:
            return None
        return SimpleNamespace(
            data=token.token_data,
            hash=token.token_hash.token_hash,
            hash_id=token.token_hash.id,
        )


def set_token_id(token_id, new_token_id):
    with get_session() as s:
        token = s.scalar(select(Token).where(Token.token_id == token_id))
        token.token_id = new_token_id


def server_key_exists(token_id, key_id):
    with get_session() as s:
        return (
            s.scalar(
                select(ServerEphemeralKey.id).where(
                    ServerEphemeralKey.token_hash_id == stored_token(token_id).hash_id,
                    ServerEphemeralKey.key_index == key_id,
                )
            )
            is not None
        )


def exchange_oauth2(stub, adapter):
    adapter.results["exchange_code"] = OAUTH2_EXCHANGE
    keypairs, public_keys = client_keys()
    response = call(
        stub,
        "ExchangeOAuth2CodeAndStore",
        publisher_pb2.ExchangeOAuth2CodeAndStoreRequest(
            platform="gmail",
            authorization_code="auth-code",
            client_ephemeral_public_keys=public_keys,
        ),
    )
    return response, keypairs


def exchange_pnba(stub, adapter):
    adapter.results["verify_code"] = PNBA_EXCHANGE
    keypairs, public_keys = client_keys()
    response = call(
        stub,
        "ExchangePNBACodeAndStore",
        publisher_pb2.ExchangePNBACodeAndStoreRequest(
            platform="telegram",
            phone_number="+237600000000",
            authorization_code="12345",
            client_ephemeral_public_keys=public_keys,
        ),
    )
    return response, keypairs


AUTH_URL_REQUEST = publisher_pb2.GetOAuth2AuthorizationUrlRequest(platform="gmail")


def test_missing_auth_headers_are_rejected(stub):
    error = rpc_error(stub, "GetOAuth2AuthorizationUrl", AUTH_URL_REQUEST, metadata=[])

    assert error.code() == grpc.StatusCode.UNAUTHENTICATED
    assert "missing required headers" in error.details()


def test_replayed_request_is_rejected(stub, adapter):
    adapter.results["create_authorization_url"] = {"url": "https://auth.example.org"}
    metadata = signed_metadata("GetOAuth2AuthorizationUrl")
    stub.GetOAuth2AuthorizationUrl(AUTH_URL_REQUEST, metadata=metadata)

    error = rpc_error(
        stub, "GetOAuth2AuthorizationUrl", AUTH_URL_REQUEST, metadata=metadata
    )

    assert error.code() == grpc.StatusCode.UNAUTHENTICATED
    assert "nonce has already been used" in error.details()


def test_request_signed_for_another_method_is_rejected(stub):
    metadata = signed_metadata("GetPNBACode")

    error = rpc_error(
        stub, "GetOAuth2AuthorizationUrl", AUTH_URL_REQUEST, metadata=metadata
    )

    assert error.code() == grpc.StatusCode.UNAUTHENTICATED
    assert "method name" in error.details()


def test_missing_required_field_is_rejected(stub):
    request = publisher_pb2.GetOAuth2AuthorizationUrlRequest()

    error = rpc_error(stub, "GetOAuth2AuthorizationUrl", request)

    assert error.code() == grpc.StatusCode.INVALID_ARGUMENT
    assert "Missing required field: platform" in error.details()


def test_unsupported_platform_is_unimplemented(stub):
    request = publisher_pb2.GetOAuth2AuthorizationUrlRequest(platform="unknown")

    error = rpc_error(stub, "GetOAuth2AuthorizationUrl", request)

    assert error.code() == grpc.StatusCode.UNIMPLEMENTED


def test_adapter_error_is_reported_as_internal(stub, adapter):
    adapter.results["create_authorization_url"] = UpstreamError("adapter crashed")

    error = rpc_error(stub, "GetOAuth2AuthorizationUrl", AUTH_URL_REQUEST)

    assert error.code() == grpc.StatusCode.INTERNAL
    assert error.details().startswith("Oops! Something went wrong")


def test_unexpected_error_hides_details(stub, monkeypatch):
    def call(*_args):
        raise RuntimeError("internal detail")

    monkeypatch.setattr(ipc, "call", call)

    error = rpc_error(stub, "GetOAuth2AuthorizationUrl", AUTH_URL_REQUEST)

    assert error.code() == grpc.StatusCode.INTERNAL
    assert "internal detail" not in error.details()


def test_other_services_skip_request_auth():
    interceptor = V1AuthInterceptor(services=[V3_SERVICE], nonce_ttl_seconds=60)

    result = interceptor.intercept(
        lambda request, context: "served",
        None,
        MagicMock(),
        "/grpc.health.v1.Health/Check",
    )

    assert result == "served"


def test_get_oauth2_authorization_url(stub, adapter):
    adapter.results["create_authorization_url"] = {
        "url": "https://auth.example.org/authorize",
        "state": "state-1",
        "code_verifier": "verifier-1",
        "client_id": "client-1",
        "scope": "email",
        "redirect_url": "https://app.example.org/callback",
    }
    request = publisher_pb2.GetOAuth2AuthorizationUrlRequest(
        platform="gmail",
        state="state-1",
        redirect_url="https://app.example.org/callback",
        autogenerate_code_verifier=True,
    )

    response = call(stub, "GetOAuth2AuthorizationUrl", request)

    assert response.authorization_url == "https://auth.example.org/authorize"
    assert response.state == "state-1"
    assert response.code_verifier == "verifier-1"
    _, method, sent = adapter.calls[-1]
    assert method == "create_authorization_url"
    assert sent.state == "state-1"
    assert sent.redirect_url == "https://app.example.org/callback"
    # Asked to generate one, the Publisher makes the PKCE verifier itself.
    assert len(sent.code_verifier) >= 43


def test_exchange_oauth2_code_stores_token(stub, adapter):
    response, keypairs = exchange_oauth2(stub, adapter)

    assert response.success
    assert response.account_identifier == "user@example.org"
    assert response.platform == "gmail"
    assert len(response.server_ephemeral_public_keys) == 256
    token = stored_token(response.token_id)
    assert token.data["account_id"] == "user@example.org"
    raw_token = decrypt_token(response, keypairs)
    assert hashlib.sha256(raw_token).digest() == token.hash


def test_exchange_oauth2_code_needs_256_client_keys(stub, adapter):
    _, public_keys = client_keys()
    request = publisher_pb2.ExchangeOAuth2CodeAndStoreRequest(
        platform="gmail",
        authorization_code="auth-code",
        client_ephemeral_public_keys=public_keys[:10],
    )

    error = rpc_error(stub, "ExchangeOAuth2CodeAndStore", request)

    assert error.code() == grpc.StatusCode.INVALID_ARGUMENT
    assert "exactly 256 keys" in error.details()


def test_exchange_oauth2_code_accepts_client_keys_in_any_order(stub, adapter):
    adapter.results["exchange_code"] = OAUTH2_EXCHANGE
    keypairs, public_keys = client_keys()
    request = publisher_pb2.ExchangeOAuth2CodeAndStoreRequest(
        platform="gmail",
        authorization_code="auth-code",
        client_ephemeral_public_keys=reversed(public_keys),
    )

    response = call(stub, "ExchangeOAuth2CodeAndStore", request)

    raw_token = decrypt_token(response, keypairs)
    assert hashlib.sha256(raw_token).digest() == stored_token(response.token_id).hash


@pytest.mark.parametrize(
    "key_ids",
    [list(range(256, 512)), [0] * 256],
    ids=["out_of_range", "duplicate"],
)
def test_exchange_oauth2_code_needs_client_key_ids_0_to_255(stub, adapter, key_ids):
    _, public_keys = client_keys()
    for key, key_id in zip(public_keys, key_ids, strict=True):
        key.key_id = key_id
    request = publisher_pb2.ExchangeOAuth2CodeAndStoreRequest(
        platform="gmail",
        authorization_code="auth-code",
        client_ephemeral_public_keys=public_keys,
    )

    error = rpc_error(stub, "ExchangeOAuth2CodeAndStore", request)

    assert error.code() == grpc.StatusCode.INVALID_ARGUMENT
    assert "each key_id 0-255 exactly once" in error.details()


def test_revoke_oauth2_token(stub, adapter):
    exchanged, keypairs = exchange_oauth2(stub, adapter)
    payload = encrypt_token(exchanged, keypairs, decrypt_token(exchanged, keypairs))
    request = publisher_pb2.RevokeOAuth2TokenRequest(
        token_id=exchanged.token_id, key_id=1
    )

    response = call(stub, "RevokeOAuth2Token", request, payload=payload)

    assert response.success
    assert stored_token(exchanged.token_id) is None
    _, method, sent = adapter.calls[-1]
    assert method == "revoke"
    assert sent.account.identifier == "user@example.org"


def test_revoke_oauth2_token_accepts_zero_ids(stub, adapter):
    exchanged, keypairs = exchange_oauth2(stub, adapter)
    set_token_id(exchanged.token_id, 0)
    payload = encrypt_token(
        exchanged, keypairs, decrypt_token(exchanged, keypairs), key_id=0
    )
    request = publisher_pb2.RevokeOAuth2TokenRequest(token_id=0, key_id=0)

    response = call(stub, "RevokeOAuth2Token", request, payload=payload)

    assert response.success
    assert stored_token(0) is None


def test_revoke_oauth2_token_with_wrong_token_is_rejected(stub, adapter):
    exchanged, keypairs = exchange_oauth2(stub, adapter)
    payload = encrypt_token(exchanged, keypairs, b"not the real token")
    request = publisher_pb2.RevokeOAuth2TokenRequest(
        token_id=exchanged.token_id, key_id=1
    )

    error = rpc_error(stub, "RevokeOAuth2Token", request, payload=payload)

    assert error.code() == grpc.StatusCode.UNAUTHENTICATED
    assert "revocation failed" in error.details()
    assert stored_token(exchanged.token_id) is not None
    assert server_key_exists(exchanged.token_id, 1)


def test_revoke_keeps_slot_when_a_later_step_fails(stub, adapter, monkeypatch):
    exchanged, keypairs = exchange_oauth2(stub, adapter)
    payload = encrypt_token(exchanged, keypairs, decrypt_token(exchanged, keypairs))
    request = publisher_pb2.RevokeOAuth2TokenRequest(
        token_id=exchanged.token_id, key_id=1
    )

    def crash(*_args):
        raise RuntimeError("database down")

    monkeypatch.setattr(revoke_oauth2_token, "mark_key_used", crash)

    error = rpc_error(stub, "RevokeOAuth2Token", request, payload=payload)

    assert error.code() == grpc.StatusCode.INTERNAL
    assert stored_token(exchanged.token_id) is not None
    assert server_key_exists(exchanged.token_id, 1)
    assert all(method != "revoke" for _, method, _ in adapter.calls)


def test_revoke_deletes_the_token_even_if_the_platform_fails(stub, adapter):
    exchanged, keypairs = exchange_oauth2(stub, adapter)
    adapter.results["revoke"] = UpstreamError("platform down")
    payload = encrypt_token(exchanged, keypairs, decrypt_token(exchanged, keypairs))
    request = publisher_pb2.RevokeOAuth2TokenRequest(
        token_id=exchanged.token_id, key_id=1
    )

    response = call(stub, "RevokeOAuth2Token", request, payload=payload)

    assert response.success
    assert stored_token(exchanged.token_id) is None


def test_get_pnba_code(stub, adapter):
    adapter.results["send_code"] = {
        "message": "Code sent",
        "expires_at": "2026-10-01T12:00:00+00:00",
    }
    request = publisher_pb2.GetPNBACodeRequest(
        platform="telegram", phone_number="+237600000000"
    )

    response = call(stub, "GetPNBACode", request)

    assert response.success
    assert response.message == "Code sent"
    expected = datetime.datetime(2026, 10, 1, 12, tzinfo=datetime.UTC)
    assert response.expires_at == int(expected.timestamp())


def test_get_pnba_code_reports_adapter_rejection(stub, adapter):
    adapter.results["send_code"] = InvalidParamsError("Invalid phone number")
    request = publisher_pb2.GetPNBACodeRequest(
        platform="telegram", phone_number="+237600000000"
    )

    error = rpc_error(stub, "GetPNBACode", request)

    assert error.code() == grpc.StatusCode.INVALID_ARGUMENT
    assert error.details() == "Invalid phone number"


def test_exchange_pnba_code_asks_for_password_with_two_step_verification(stub, adapter):
    adapter.results["verify_code"] = {"password_required": True}
    _, public_keys = client_keys()
    request = publisher_pb2.ExchangePNBACodeAndStoreRequest(
        platform="telegram",
        phone_number="+237600000000",
        authorization_code="12345",
        client_ephemeral_public_keys=public_keys,
    )

    response = call(stub, "ExchangePNBACodeAndStore", request)

    assert response.success
    assert response.two_step_verification_enabled
    assert not response.token_ciphertext
    with get_session() as s:
        assert s.scalar(select(func.count(Token.id))) == 0


def test_a_rejected_code_reaches_the_client(stub, adapter):
    adapter.results["verify_code"] = AuthenticationError("Wrong code.")
    _, public_keys = client_keys()
    request = publisher_pb2.ExchangePNBACodeAndStoreRequest(
        platform="telegram",
        phone_number="+237600000000",
        authorization_code="0",
        client_ephemeral_public_keys=public_keys,
    )

    error = rpc_error(stub, "ExchangePNBACodeAndStore", request)

    assert error.code() == grpc.StatusCode.INVALID_ARGUMENT
    assert error.details() == "Wrong code."


def test_a_rate_limited_adapter_is_resource_exhausted(stub, adapter):
    adapter.results["send_code"] = RateLimitedError("Slow down.", retry_after=30)
    request = publisher_pb2.GetPNBACodeRequest(
        platform="telegram", phone_number="+237600000000"
    )

    error = rpc_error(stub, "GetPNBACode", request)

    assert error.code() == grpc.StatusCode.RESOURCE_EXHAUSTED


def test_exchange_pnba_code_checks_the_password(stub, adapter):
    adapter.results["verify_password"] = PNBA_EXCHANGE
    _, public_keys = client_keys()
    request = publisher_pb2.ExchangePNBACodeAndStoreRequest(
        platform="telegram",
        phone_number="+237600000000",
        authorization_code="12345",
        password="pw",
        client_ephemeral_public_keys=public_keys,
    )

    response = call(stub, "ExchangePNBACodeAndStore", request)

    assert response.token_ciphertext
    _, method, sent = adapter.calls[-1]
    assert (method, sent.password) == ("verify_password", "pw")


def test_exchange_pnba_code_stores_session(stub, adapter):
    response, keypairs = exchange_pnba(stub, adapter)

    assert response.success
    assert response.account_identifier == "+237600000000"
    token = stored_token(response.token_id)
    assert token.data["token"] == {"session_string": "session-data"}
    raw_token = decrypt_token(response, keypairs)
    assert hashlib.sha256(raw_token).digest() == token.hash


def test_revoke_pnba_token(stub, adapter):
    exchanged, keypairs = exchange_pnba(stub, adapter)
    payload = encrypt_token(exchanged, keypairs, decrypt_token(exchanged, keypairs))
    request = publisher_pb2.RevokePNBATokenRequest(
        token_id=exchanged.token_id, key_id=1
    )

    response = call(stub, "RevokePNBAToken", request, payload=payload)

    assert response.success
    assert stored_token(exchanged.token_id) is None
    _, method, sent = adapter.calls[-1]
    assert method == "revoke"
    assert sent.account.token == {"session_string": "session-data"}


def test_sync_keys_replaces_the_key_pool(stub, adapter):
    exchanged, keypairs = exchange_oauth2(stub, adapter)
    payload = encrypt_token(exchanged, keypairs, decrypt_token(exchanged, keypairs))
    _, new_public_keys = client_keys()
    request = publisher_pb2.SyncKeysRequest(
        token_id=exchanged.token_id,
        key_id=1,
        client_ephemeral_public_keys=new_public_keys,
    )

    response = call(stub, "SyncKeys", request, payload=payload)

    assert response.success
    old_keys = {k.public_key for k in exchanged.server_ephemeral_public_keys}
    new_keys = {k.public_key for k in response.server_ephemeral_public_keys}
    assert len(new_keys) == 256
    assert not old_keys & new_keys
    token_hash_id = stored_token(exchanged.token_id).hash_id
    with get_session() as s:
        pool_size = s.scalar(
            select(func.count(ServerEphemeralKey.id)).where(
                ServerEphemeralKey.token_hash_id == token_hash_id
            )
        )
    assert pool_size == 256


def test_sync_keys_accepts_zero_ids(stub, adapter):
    exchanged, keypairs = exchange_oauth2(stub, adapter)
    set_token_id(exchanged.token_id, 0)
    payload = encrypt_token(
        exchanged, keypairs, decrypt_token(exchanged, keypairs), key_id=0
    )
    _, new_public_keys = client_keys()
    request = publisher_pb2.SyncKeysRequest(
        token_id=0, key_id=0, client_ephemeral_public_keys=new_public_keys
    )

    response = call(stub, "SyncKeys", request, payload=payload)

    assert response.success


def test_sync_keys_with_wrong_token_is_rejected(stub, adapter):
    exchanged, keypairs = exchange_oauth2(stub, adapter)
    payload = encrypt_token(exchanged, keypairs, b"not the real token")
    _, new_public_keys = client_keys()
    request = publisher_pb2.SyncKeysRequest(
        token_id=exchanged.token_id,
        key_id=1,
        client_ephemeral_public_keys=new_public_keys,
    )

    error = rpc_error(stub, "SyncKeys", request, payload=payload)

    assert error.code() == grpc.StatusCode.UNAUTHENTICATED
    assert "sync failed" in error.details()
