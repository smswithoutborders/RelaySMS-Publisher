# SPDX-License-Identifier: GPL-3.0-only
"""Server identity keys and the per-token ephemeral key pools."""

import hashlib
import logging
import secrets

from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey
from sqlalchemy import delete, func, insert, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

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


class KeyManagementError(PublisherError):
    pass


class KeyNotFoundError(KeyManagementError):
    pass


class KeyUnavailableError(KeyManagementError):
    pass


class TokenVerificationError(KeyManagementError):
    pass


def initialize_server_identity_keys(session: Session, count: int = 256) -> None:
    """Create database identity keys if they don't exist yet."""
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

    Slots 0-15 are reserved, so the token's slot is picked from 16-255.
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
    """Replace the token's key pools; return the server public keys by slot."""
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
                "used": False,
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
                "used": False,
            }
            for k in client_public_keys
            if k.key_id != skip
        ],
    )
    return server_keypairs, server_public_keys


def pop_keys(
    session: Session, token_hash_id: int, key_id: int
) -> tuple[bytes, bytes, bytes, bytes]:
    """Delete and return a slot's keys: ss_kid, es_kid, es_kid_pk, ec_kid_pk."""
    se_row = session.execute(
        delete(ServerEphemeralKey)
        .where(
            ServerEphemeralKey.token_hash_id == token_hash_id,
            ServerEphemeralKey.key_index == key_id,
        )
        .returning(ServerEphemeralKey.private_key, ServerEphemeralKey.public_key)
    ).first()
    if not se_row:
        logger.error(
            "Server ephemeral key unavailable: token_hash_id=%s, kid=%s",
            token_hash_id,
            key_id,
        )
        raise KeyUnavailableError("Server ephemeral key already used or missing")

    ce_row = session.execute(
        delete(ClientEphemeralKey)
        .where(
            ClientEphemeralKey.token_hash_id == token_hash_id,
            ClientEphemeralKey.key_index == key_id,
        )
        .returning(ClientEphemeralKey.public_key)
    ).first()
    if not ce_row:
        logger.error(
            "Client ephemeral key unavailable: token_hash_id=%s, kid=%s",
            token_hash_id,
            key_id,
        )
        raise KeyUnavailableError("Client ephemeral key already used or missing")

    ss_kid = get_private_key(session, key_id).private_bytes_raw()
    logger.debug(
        "Keys consumed for decryption: token_hash_id=%s, kid=%s",
        token_hash_id,
        key_id,
    )
    return ss_kid, se_row.private_key, se_row.public_key, ce_row.public_key


def pop_token_keys(
    session: Session, token_id: int, key_id: int
) -> tuple[Token, TokenHash, bytes, bytes, bytes, bytes]:
    """Resolve a token by id, then pop the slot's keys for decrypting its payload."""
    token = session.scalar(select(Token).where(Token.token_id == token_id))
    if token is None:
        logger.error("Token not found: token_id=%s", token_id)
        raise KeyNotFoundError("Token not found")

    token_hash = token.token_hash
    if token_hash is None:
        logger.error("Token hash missing for token_id=%s", token_id)
        raise KeyNotFoundError("Token hash not found", platform_name=token.platform)

    try:
        keys = pop_keys(session, token_hash.id, key_id)
    except KeyUnavailableError as exc:
        exc.platform_name = token.platform
        raise
    return token, token_hash, *keys


def verify_token(
    session: Session, token_id: int, key_id: int, ciphertext: bytes
) -> Token:
    """Pop the slot's keys, decrypt the client's token and check its hash."""
    token, token_hash, ss_kid, es_kid, _, ec_kid_pk = pop_token_keys(
        session, token_id, key_id
    )

    try:
        decrypted = rrs.v1_token_decrypt_server(
            ss_kid=ss_kid,
            es_kid=es_kid,
            ec_kid_pk=ec_kid_pk,
            key_id=key_id,
            ciphertext=ciphertext,
        )
        valid = secrets.compare_digest(
            hashlib.sha256(decrypted).digest(), token_hash.token_hash
        )
    except rrs.V1CryptographicError.FailedToDecrypt:
        valid = False

    if not valid:
        logger.warning("Token verification failed: kid=%s", key_id)
        raise TokenVerificationError(
            "Token verification failed", platform_name=token.platform
        )
    return token
