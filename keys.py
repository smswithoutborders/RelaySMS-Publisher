# SPDX-License-Identifier: GPL-3.0-only
"""Key management functions."""

from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey
from sqlalchemy import func, insert, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from db import get_session
from logutils import get_logger
from models.client_ephemeral_key import ClientEphemeralKey
from models.server_ephemeral_key import ServerEphemeralKey
from models.server_identity_key import ServerIdentityKey, get_private_key
from models.token import Token
from models.token_hash import TokenHash

logger = get_logger(__name__)


def initialize_server_identity_keys(count: int = 256) -> None:
    """Generate and store server identity keys on first startup."""
    with get_session() as s:
        existing = s.scalar(select(func.count(ServerIdentityKey.id)))
        if existing > 0:
            logger.info(
                "Server identity keys already exist (%d keys), skipping", existing
            )
            return

        logger.info("Generating %d server identity keys ...", count)
        try:
            keypairs = [X25519PrivateKey.generate() for _ in range(count)]
            s.execute(
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
            logger.info(
                "Successfully generated and stored %d server identity keys", count
            )
        except IntegrityError:
            logger.info(
                "Server identity keys already created by another process, skipping"
            )
        except Exception as e:
            logger.error("Failed to generate server identity keys: %s", e)
            raise


def get_keys_for_decryption(
    token_id: int, key_id: int, session: Session
) -> tuple[Token, TokenHash, bytes, bytes, bytes, bytes]:
    """
    Fetch token and all necessary keys for decryption.
    Returns (Token, TokenHash, ss_kid, es_kid, es_kid_pk, ec_kid_pk).
    """
    token = session.scalar(select(Token).where(Token.token_id == token_id))
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
