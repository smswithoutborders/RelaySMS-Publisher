# SPDX-License-Identifier: GPL-3.0-only
"""Key management module."""

import hashlib
import logging
import secrets

from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey
from sqlalchemy import delete, func, insert, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from lib_relaysms_payload_specs.generated import relaysms_spec_payload as rrs
from publisher.errors import PlatformAwareError
from publisher.models.client_ephemeral_key import ClientEphemeralKey
from publisher.models.server_ephemeral_key import ServerEphemeralKey
from publisher.models.server_identity_key import ServerIdentityKey, get_private_key
from publisher.models.server_identity_key import mark_key_used as mark_ss_kid_used
from publisher.models.token import Token
from publisher.models.token_hash import TokenHash
from publisher.models.token_hash import create as create_token_hash

logger = logging.getLogger(__name__)


class KeyManagerError(PlatformAwareError):
    pass


class KeyNotFoundError(KeyManagerError):
    pass


class KeyUnavailableError(KeyManagerError):
    pass


class TokenVerificationError(KeyManagerError):
    pass


class KeyManager:
    """Manages decryption keys."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def initialize_server_identity_keys(self, count: int = 256) -> None:
        """Create database identity keys if they don't exist yet."""
        existing = self.session.execute(
            select(func.count(ServerIdentityKey.id))
        ).scalar_one()
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

    def create_token_pools_and_encrypt(
        self, token_pk_id: int, client_public_keys: list
    ) -> tuple[bytes, int, list[bytes]]:
        """Create the token's hash and key pools, and encrypt the token to one slot.

        Slots 0-15 are reserved, so the token's slot is picked from 16-255.
        """
        token_hash, raw_token = create_token_hash(
            token_pk_id=token_pk_id, session=self.session
        )
        kid_index = secrets.randbelow(240) + 16
        server_keypairs, server_public_keys = self._insert_pools(
            token_hash.id, client_public_keys, skip=kid_index
        )

        token_ciphertext = rrs.v1_token_encrypt_server(
            ss_kid=get_private_key(kid_index, self.session).private_bytes_raw(),
            es_kid=server_keypairs[kid_index].private_bytes_raw(),
            ec_kid_pk=client_public_keys[kid_index].public_key,
            key_id=kid_index,
            token=raw_token,
        )
        self.mark_identity_key_used(kid_index)
        return token_ciphertext, kid_index, server_public_keys

    def sync_token_pools(
        self, token_hash: TokenHash, client_public_keys: list
    ) -> list[bytes]:
        """Replace the token's key pools; return the server public keys by slot."""
        self.session.execute(
            delete(ServerEphemeralKey).where(
                ServerEphemeralKey.token_hash_id == token_hash.id
            )
        )
        self.session.execute(
            delete(ClientEphemeralKey).where(
                ClientEphemeralKey.token_hash_id == token_hash.id
            )
        )
        _, server_public_keys = self._insert_pools(token_hash.id, client_public_keys)
        return server_public_keys

    def _insert_pools(
        self, token_hash_id: int, client_public_keys: list, skip: int | None = None
    ) -> tuple[list[X25519PrivateKey], list[bytes]]:
        """Generate 256 server key pairs and store both pools, minus slot `skip`."""
        server_keypairs = [X25519PrivateKey.generate() for _ in range(256)]
        server_public_keys = [
            kp.public_key().public_bytes_raw() for kp in server_keypairs
        ]

        self.session.execute(
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
        self.session.execute(
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

    def verify_token(self, token_id: int, key_id: int, ciphertext: bytes) -> Token:
        """Pop the slot's keys, decrypt the client's token and check its hash."""
        token, token_hash, ss_kid, es_kid, _, ec_kid_pk = (
            self.get_token_and_keys_for_decryption(token_id=token_id, key_id=key_id)
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

    def mark_identity_key_used(self, key_id: int) -> None:
        """Mark a server identity key as used."""
        mark_ss_kid_used(key_id, self.session)
        logger.debug("Marked identity key used: kid=%s", key_id)
