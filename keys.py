# SPDX-License-Identifier: GPL-3.0-only
"""Key management module."""

from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey
from sqlalchemy import delete, func, insert, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from logutils import get_logger
from models.client_ephemeral_key import ClientEphemeralKey
from models.server_ephemeral_key import ServerEphemeralKey
from models.server_identity_key import ServerIdentityKey, get_private_key
from models.server_identity_key import mark_key_used as mark_ss_kid_used
from models.token import Token
from models.token_hash import TokenHash
from utils import PlatformAwareError

logger = get_logger(__name__)


class KeyManagerError(PlatformAwareError):
    pass


class KeyNotFoundError(KeyManagerError):
    pass


class KeyUnavailableError(KeyManagerError):
    pass


class KeyManager:
    """Manages decryption keys."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def initialize_server_identity_keys(self, count: int = 256) -> None:
        """Create database identity keys if they don't exist yet."""
        existing = self.session.scalar(select(func.count(ServerIdentityKey.id)))
        if existing > 0:
            logger.info("Server identity keys exist (%d found), skipping", existing)
            return

        logger.info("Generating %d server identity keys", count)
        try:
            keypairs = [X25519PrivateKey.generate() for _ in range(count)]
            self.session.execute(
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
            raise KeyManagerError("Server identity key setup failed") from exc

    def get_keys_for_decryption(
        self, token_hash_id: int, key_id: int
    ) -> tuple[bytes, bytes, bytes, bytes]:
        """Pop and return the keys needed to decrypt a message."""
        se_row = self.session.execute(
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

        ce_row = self.session.execute(
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

        ss_kid = get_private_key(key_id, self.session).private_bytes_raw()
        logger.debug(
            "Keys consumed for decryption: token_hash_id=%s, kid=%s",
            token_hash_id,
            key_id,
        )
        return ss_kid, se_row.private_key, se_row.public_key, ce_row.public_key

    def get_token_and_keys_for_decryption(
        self, token_id: int, key_id: int
    ) -> tuple[Token, TokenHash, bytes, bytes, bytes, bytes]:
        """Resolve a token by id, then pop the keys needed to decrypt its payload."""
        token = self.session.scalar(select(Token).where(Token.token_id == token_id))
        if token is None:
            logger.error("Token not found: token_id=%s", token_id)
            raise KeyNotFoundError("Token not found")

        token_hash_obj = token.token_hash
        if token_hash_obj is None:
            logger.error("Token hash missing for token_id=%s", token_id)
            raise KeyNotFoundError("Token hash not found", platform_name=token.platform)

        try:
            ss_kid, se_private, se_public, ce_public = self.get_keys_for_decryption(
                token_hash_id=token_hash_obj.id, key_id=key_id
            )
        except KeyUnavailableError as exc:
            exc.platform_name = token.platform
            raise
        return token, token_hash_obj, ss_kid, se_private, se_public, ce_public

    def mark_identity_key_used(self, key_id: int) -> None:
        """Mark a server identity key as used."""
        mark_ss_kid_used(key_id, self.session)
        logger.debug("Marked identity key used: kid=%s", key_id)
