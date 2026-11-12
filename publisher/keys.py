# SPDX-License-Identifier: GPL-3.0-only
"""Server identity keys and the per-token ephemeral key pools."""

import hashlib
import logging
import secrets
from dataclasses import dataclass
from typing import cast

from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey
from sqlalchemy import CursorResult, and_, delete, func, insert, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, contains_eager

from lib_relaysms_payload_specs.generated import relaysms_spec_payload as rrs
from publisher.errors import PublisherError
from publisher.models.client_ephemeral_key import ClientEphemeralKey
from publisher.models.server_ephemeral_key import ServerEphemeralKey
from publisher.models.server_identity_key import (
    ServerIdentityKey,
    get_private_key,
    mark_key_used,
)
from publisher.models.token import Token
from publisher.models.token_hash import TokenHash
from publisher.models.token_hash import create as create_token_hash

logger = logging.getLogger(__name__)

_STAND_IN_KEYS = (
    X25519PrivateKey.generate().private_bytes_raw(),
    X25519PrivateKey.generate().private_bytes_raw(),
    X25519PrivateKey.generate().public_key().public_bytes_raw(),
)


class KeyManagementError(PublisherError):
    pass


class KeyNotFoundError(KeyManagementError):
    pass


class KeyUnavailableError(KeyManagementError):
    pass


class TokenVerificationError(KeyManagementError):
    pass


def initialize_server_identity_keys(session: Session, count: int = 256) -> None:
    """Create the server identity keys if none exist."""
    existing = session.execute(select(func.count(ServerIdentityKey.id))).scalar_one()
    if existing > 0:
        logger.info("Server identity keys exist (%d found), skipping", existing)
        return

    logger.info("Generating %d server identity keys", count)
    try:
        keypairs = [X25519PrivateKey.generate() for _ in range(count)]
        session.execute(
            insert(ServerIdentityKey),
            [
                {
                    "key_index": i,
                    "private_key": kp.private_bytes_raw(),
                    "public_key": kp.public_key().public_bytes_raw(),
                }
                for i, kp in enumerate(keypairs)
            ],
        )
        logger.info("Saved %d server identity keys", count)
    except IntegrityError:
        logger.info("Server identity keys were created by another worker, skipping")
    except Exception as exc:
        logger.exception("Failed to generate server identity keys")
        raise KeyManagementError("Server identity key setup failed") from exc


def create_token_pools_and_encrypt(
    session: Session, token_pk_id: int, client_public_keys: list
) -> tuple[bytes, int, list[bytes]]:
    """Create the token's hash and key pools, and encrypt the token to one slot.

    The token's slot is picked from 16-255 (0-15 are reserved).
    """
    token_hash, raw_token = create_token_hash(session, token_pk_id)
    kid_index = secrets.randbelow(240) + 16
    server_keypairs, server_public_keys = _insert_pools(
        session, token_hash.id, client_public_keys, skip=kid_index
    )

    token_ciphertext = rrs.v1_token_encrypt_server(
        ss_kid=get_private_key(session, kid_index).private_bytes_raw(),
        es_kid=server_keypairs[kid_index].private_bytes_raw(),
        ec_kid_pk=next(
            k.public_key for k in client_public_keys if k.key_id == kid_index
        ),
        key_id=kid_index,
        token=raw_token,
    )
    mark_key_used(session, kid_index)
    return token_ciphertext, kid_index, server_public_keys


def sync_token_pools(
    session: Session, token_hash: TokenHash, client_public_keys: list
) -> list[bytes]:
    """Replace the token's key pools and return the server public keys by slot."""
    session.execute(
        delete(ServerEphemeralKey).where(
            ServerEphemeralKey.token_hash_id == token_hash.id
        )
    )
    session.execute(
        delete(ClientEphemeralKey).where(
            ClientEphemeralKey.token_hash_id == token_hash.id
        )
    )
    _, server_public_keys = _insert_pools(session, token_hash.id, client_public_keys)
    return server_public_keys


def _insert_pools(
    session: Session,
    token_hash_id: int,
    client_public_keys: list,
    skip: int | None = None,
) -> tuple[list[X25519PrivateKey], list[bytes]]:
    """Generate 256 server key pairs and store both pools, minus slot `skip`."""
    server_keypairs = [X25519PrivateKey.generate() for _ in range(256)]
    server_public_keys = [kp.public_key().public_bytes_raw() for kp in server_keypairs]

    session.execute(
        insert(ServerEphemeralKey),
        [
            {
                "token_hash_id": token_hash_id,
                "key_index": i,
                "private_key": kp.private_bytes_raw(),
                "public_key": server_public_keys[i],
            }
            for i, kp in enumerate(server_keypairs)
            if i != skip
        ],
    )
    session.execute(
        insert(ClientEphemeralKey),
        [
            {
                "token_hash_id": token_hash_id,
                "key_index": k.key_id,
                "public_key": k.public_key,
            }
            for k in client_public_keys
            if k.key_id != skip
        ],
    )
    return server_keypairs, server_public_keys


@dataclass(frozen=True)
class TokenSlot:
    """A token and the keys of one of its slots, not yet used."""

    token: Token
    ss_kid: bytes
    server_key: ServerEphemeralKey
    client_key: ClientEphemeralKey


def get_token_slot(session: Session, token_id: int, key_id: int) -> TokenSlot:
    """Load a token and a slot's keys without consuming them.

    For a key ID in 0-255, runs the same two queries whether or not the token
    or slot exists.
    """
    if not 0 <= key_id <= 255:
        logger.warning("Key ID out of range: token_id=%s, kid=%s", token_id, key_id)
        raise KeyUnavailableError("Ephemeral key already used or missing")

    ss_kid = get_private_key(session, key_id).private_bytes_raw()
    query = (
        select(Token, ServerEphemeralKey, ClientEphemeralKey)
        .outerjoin(Token.token_hash)
        .options(contains_eager(Token.token_hash))
        .where(Token.token_id == token_id)
    )
    for model in (ServerEphemeralKey, ClientEphemeralKey):
        query = query.outerjoin(
            model, and_(model.token_hash_id == TokenHash.id, model.key_index == key_id)
        )
    row = session.execute(query).first()

    if row is None:
        logger.error("Token not found: token_id=%s", token_id)
        raise KeyNotFoundError("Token not found")

    token, server_key, client_key = row
    if token.token_hash is None:
        logger.error("Token hash missing for token_id=%s", token_id)
        raise KeyNotFoundError("Token hash not found", platform_name=token.platform)

    if server_key is None or client_key is None:
        logger.error(
            "Ephemeral key unavailable: token_hash_id=%s, kid=%s",
            token.token_hash.id,
            key_id,
        )
        raise KeyUnavailableError(
            "Ephemeral key already used or missing", platform_name=token.platform
        )
    return TokenSlot(token, ss_kid, server_key, client_key)


def consume_token_slot(session: Session, slot: TokenSlot) -> None:
    """Delete a slot's keys, or raise KeyUnavailableError if another worker did."""
    for row in (slot.server_key, slot.client_key):
        model = type(row)
        deleted = cast(
            CursorResult, session.execute(delete(model).where(model.id == row.id))
        )
        if not deleted.rowcount:
            logger.error(
                "Ephemeral key consumed by another worker: token_hash_id=%s, kid=%s",
                row.token_hash_id,
                row.key_index,
            )
            raise KeyUnavailableError(
                "Ephemeral key already used or missing",
                platform_name=slot.token.platform,
            )
    logger.debug(
        "Keys consumed: token_hash_id=%s, kid=%s",
        slot.server_key.token_hash_id,
        slot.server_key.key_index,
    )


def _token_matches(
    ss_kid: bytes,
    es_kid: bytes,
    ec_kid_pk: bytes,
    key_id: int,
    ciphertext: bytes,
    token_hash: bytes,
) -> bool:
    try:
        decrypted = rrs.v1_token_decrypt_server(
            ss_kid=ss_kid,
            es_kid=es_kid,
            ec_kid_pk=ec_kid_pk,
            key_id=key_id,
            ciphertext=ciphertext,
        )
    except rrs.V1CryptographicError.FailedToDecrypt:
        return False
    return secrets.compare_digest(hashlib.sha256(decrypted).digest(), token_hash)


def redeem_token(
    session: Session, token_id: int, key_id: int, ciphertext: bytes
) -> Token:
    """Check the client's token against a slot, then use up the slot's keys."""
    try:
        slot = get_token_slot(session, token_id, key_id)
    except KeyManagementError:
        # Decrypt with throwaway keys, the same work as checking a wrong token.
        _token_matches(*_STAND_IN_KEYS, 0, ciphertext, bytes(32))
        raise

    if not _token_matches(
        slot.ss_kid,
        slot.server_key.private_key,
        slot.client_key.public_key,
        key_id,
        ciphertext,
        slot.token.token_hash.token_hash,
    ):
        logger.warning("Token verification failed: kid=%s", key_id)
        raise TokenVerificationError(
            "Token verification failed", platform_name=slot.token.platform
        )

    consume_token_slot(session, slot)
    return slot.token
