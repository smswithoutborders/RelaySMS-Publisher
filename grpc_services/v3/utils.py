# SPDX-License-Identifier: GPL-3.0-only
"""Shared utilities for V3 gRPC service handlers."""

import secrets
import threading
import time

import grpc
from cachetools import TTLCache
from cryptography.hazmat.primitives.asymmetric.x25519 import (
    X25519PrivateKey,
    X25519PublicKey,
)
from sqlalchemy import delete, insert, select
from sqlalchemy.orm import Session

from db import get_session
from lib_relaysms_payload_specs.generated import relaysms_spec_payload as rrs
from logutils import get_logger
from models.client_ephemeral_key import ClientEphemeralKey
from models.server_ephemeral_key import ServerEphemeralKey
from models.server_identity_key import get_private_key, mark_key_used
from models.token import Token
from models.token_hash import TokenHash
from models.token_hash import create as create_token_hash
from platforms.adapter_manager import AdapterManager, PlatformManifest
from protos.v3 import publisher_pb2

logger = get_logger(__name__)


def get_keys_for_decryption(
    token_id_bytes: bytes, key_id: int, session: Session
) -> tuple[Token, TokenHash, bytes, bytes, bytes, bytes]:
    """
    Fetch token and all necessary keys for decryption.
    Returns (Token, TokenHash, ss_kid, es_kid, es_kid_pk, ec_kid_pk).
    """
    token = session.scalar(select(Token).where(Token.token_id == token_id_bytes))
    if not token:
        raise ValueError("token not found")

    token_hash_obj = session.scalar(
        select(TokenHash).where(TokenHash.token_id == token.id)
    )
    if not token_hash_obj:
        raise ValueError("token hash not found")

    se_key = session.scalar(
        select(ServerEphemeralKey).where(
            ServerEphemeralKey.token_hash_id == token_hash_obj.id,
            ServerEphemeralKey.key_index == key_id,
        )
    )
    if not se_key:
        raise ValueError(f"server ephemeral key not found: kid={key_id}")

    ce_key = session.scalar(
        select(ClientEphemeralKey).where(
            ClientEphemeralKey.token_hash_id == token_hash_obj.id,
            ClientEphemeralKey.key_index == key_id,
        )
    )
    if not ce_key:
        raise ValueError(f"client ephemeral key not found: kid={key_id}")

    ss_kid = get_private_key(key_id, session).private_bytes_raw()

    return (
        token,
        token_hash_obj,
        ss_kid,
        se_key.private_key,
        se_key.public_key,
        ce_key.public_key,
    )


def get_oauth2_adapter(manager: AdapterManager, platform: str) -> PlatformManifest:
    """Resolve the OAuth2 adapter for a platform or raise NotImplementedError."""
    adapter = manager.list_adapters(name=platform.lower(), proto_id=0)
    if not adapter:
        raise NotImplementedError(
            f"Platform '{platform.lower()}' with protocol 'oauth2' is not supported. "
            "Contact the developers for implementation status."
        )
    return adapter[0]


def get_pnba_adapter(manager: AdapterManager, platform: str) -> PlatformManifest:
    """Resolve the PNBA adapter for a platform or raise NotImplementedError."""
    adapter = manager.list_adapters(name=platform.lower(), proto_id=1)
    if not adapter:
        raise NotImplementedError(
            f"Platform '{platform.lower()}' with protocol 'pnba' is not supported. "
            "Contact the developers for implementation status."
        )
    return adapter[0]


def verify_v1_request(
    context: grpc.ServicerContext,
    nonce_cache: TTLCache,
    nonce_lock: threading.Lock,
    nonce_cache_ttl: int,
) -> tuple[rrs.ResponsePayload | None, str | None]:
    """Verify and decrypt an incoming V1 encrypted request."""
    metadata = dict(context.invocation_metadata())

    ciphertext = metadata.get("x-payload-bin")
    ec_pk = metadata.get("x-public-key-bin")
    key_id_raw = metadata.get("x-key-id")
    nonce = metadata.get("x-nonce-bin")
    timestamp_raw = metadata.get("x-timestamp")

    missing = [
        name
        for name, val in [
            ("x-payload-bin", ciphertext),
            ("x-public-key-bin", ec_pk),
            ("x-key-id", key_id_raw),
            ("x-nonce-bin", nonce),
            ("x-timestamp", timestamp_raw),
        ]
        if not val
    ]
    if missing:
        reason = f"missing required headers: {', '.join(missing)}"
        logger.warning(reason)
        return None, reason

    try:
        key_id = int(key_id_raw)
    except (ValueError, TypeError):
        return None, "x-key-id is not a valid integer"

    try:
        timestamp = int(timestamp_raw)
    except ValueError:
        return None, "x-timestamp is not a valid integer"

    timestamp_diff = abs(int(time.time()) - timestamp)
    if timestamp_diff > nonce_cache_ttl:
        logger.warning(
            "outdated timestamp (diff=%ds, window=%ds)", timestamp_diff, nonce_cache_ttl
        )
        return None, "outdated timestamp detected in request"

    with nonce_lock:
        if nonce in nonce_cache:
            logger.warning("replayed nonce detected")
            return None, "nonce has already been used"
        nonce_cache[nonce] = True

    try:
        with get_session() as s:
            ss_kid = get_private_key(key_id, s).private_bytes_raw()
    except ValueError as e:
        logger.warning("key lookup failed for key_id=%s: %s", key_id, e)
        return None, str(e)

    try:
        return rrs.v1_requests_decrypt(
            ss_kid=ss_kid, ec_pk=ec_pk, nonce=nonce, ciphertext=ciphertext
        ), None
    except rrs.V1CryptographicError.FailedToDecrypt as e:
        logger.warning("v1_requests_decrypt failed for key_id=%s: %s", key_id, e)
        return None, "decryption failed"


def validate_client_ephemeral_public_keys(keys) -> str | None:
    """Validate client ephemeral public keys format and count."""
    if len(keys) != 256:
        return f"client_ephemeral_public_keys must contain exactly 256 keys, got {len(keys)}"
    for key_obj in keys:
        if len(key_obj.public_key) != 32:
            return (
                f"Invalid key for key_id {key_obj.key_id}: "
                f"must be 32 bytes, got {len(key_obj.public_key)}"
            )
        try:
            X25519PublicKey.from_public_bytes(key_obj.public_key)
        except Exception as e:
            return f"Invalid cryptographic key for key_id {key_obj.key_id}: {e}"
    return None


def create_token_pools_and_encrypt(
    token_id: int, client_ephemeral_public_keys: list, session: Session
) -> tuple[bytes, int, list[publisher_pb2.PublicKey]]:
    """
    Create 256 server and client ephemeral key pools, pick a single random
    kid_index in the range [16, 255] across all three key roles (ss, es, ec),
    encrypt the raw token, and mark the identity key used.

    kid_index 0-15 are reserved and never selected.
    """
    token_hash_obj, raw_token = create_token_hash(token_id=token_id, session=session)

    kid_index = secrets.randbelow(240) + 16

    server_keypairs = [X25519PrivateKey.generate() for _ in range(256)]

    server_public_keys = [
        publisher_pb2.PublicKey(key_id=i, public_key=kp.public_key().public_bytes_raw())
        for i, kp in enumerate(server_keypairs)
    ]

    session.execute(
        insert(ServerEphemeralKey),
        [
            {
                "token_hash_id": token_hash_obj.id,
                "key_index": i,
                "private_key": kp.private_bytes_raw(),
                "public_key": server_public_keys[i].public_key,
                "used": False,
            }
            for i, kp in enumerate(server_keypairs)
            if i != kid_index
        ],
    )

    session.execute(
        insert(ClientEphemeralKey),
        [
            {
                "token_hash_id": token_hash_obj.id,
                "key_index": k.key_id,
                "public_key": k.public_key,
                "used": False,
            }
            for k in client_ephemeral_public_keys
            if k.key_id != kid_index
        ],
    )

    ss_kid_bytes = get_private_key(kid_index, session).private_bytes_raw()
    es_kid_bytes = server_keypairs[kid_index].private_bytes_raw()
    ec_kid_pk_bytes = client_ephemeral_public_keys[kid_index].public_key

    token_ciphertext = rrs.v1_token_encrypt_server(
        ss_kid=ss_kid_bytes,
        es_kid=es_kid_bytes,
        ec_kid_pk=ec_kid_pk_bytes,
        key_id=kid_index,
        token=raw_token,
    )

    mark_key_used(kid_index, session)

    return token_ciphertext, kid_index, server_public_keys


def sync_token_pools(
    token_hash_obj: TokenHash, client_ephemeral_public_keys: list, session: Session
) -> list[publisher_pb2.PublicKey]:
    """
    Clear old server and client ephemeral key pools, create 256 new ones,
    and save them all to the database.
    """
    session.execute(
        delete(ServerEphemeralKey).where(
            ServerEphemeralKey.token_hash_id == token_hash_obj.id
        )
    )
    session.execute(
        delete(ClientEphemeralKey).where(
            ClientEphemeralKey.token_hash_id == token_hash_obj.id
        )
    )

    server_keypairs = [X25519PrivateKey.generate() for _ in range(256)]

    server_public_keys = [
        publisher_pb2.PublicKey(key_id=i, public_key=kp.public_key().public_bytes_raw())
        for i, kp in enumerate(server_keypairs)
    ]

    session.execute(
        insert(ServerEphemeralKey),
        [
            {
                "token_hash_id": token_hash_obj.id,
                "key_index": i,
                "private_key": kp.private_bytes_raw(),
                "public_key": server_public_keys[i].public_key,
                "used": False,
            }
            for i, kp in enumerate(server_keypairs)
        ],
    )

    session.execute(
        insert(ClientEphemeralKey),
        [
            {
                "token_hash_id": token_hash_obj.id,
                "key_index": k.key_id,
                "public_key": k.public_key,
                "used": False,
            }
            for k in client_ephemeral_public_keys
        ],
    )

    return server_public_keys
