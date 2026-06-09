# SPDX-License-Identifier: GPL-3.0-only
"""Keypair generation."""

from typing import List, Optional, Tuple

from sqlalchemy.orm import Session

from db import get_session
from models.server_ephemeral_key import ServerEphemeralKey
from models.token_hash import TokenHash
from models.token_hash import create as create_token_hash
from utils import get_logger

logger = get_logger(__name__)


def generate_x25519_keypair() -> Tuple[bytes, bytes]:
    """Generate a single X25519 keypair.

    Returns:
        Tuple of (private_key, public_key) as 32-byte values
    """
    try:
        from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey
    except ImportError:
        raise ImportError(
            "cryptography package required for X25519 key generation. "
            "Install with: pip install cryptography"
        )

    private_key = X25519PrivateKey.generate()
    public_key = private_key.public_key()

    return (
        private_key.private_bytes_raw(),
        public_key.public_bytes_raw(),
    )


def generate_keypair_pool(count: int = 256) -> List[Tuple[bytes, bytes]]:
    """Generate multiple X25519 keypairs efficiently.

    Args:
        count: Number of keypairs to generate (default: 256)

    Returns:
        List of (private_key, public_key) tuples
    """
    logger.info("Generating %d X25519 keypairs...", count)
    keypairs = [generate_x25519_keypair() for _ in range(count)]
    logger.info("Generated %d keypairs", len(keypairs))
    return keypairs


def create_ephemeral_key_pool(
    token_hash_id: int, count: int = 256, session: Optional[Session] = None
) -> int:
    """Create a pool of ephemeral keys for a token hash.

    Args:
        token_hash_id: ID of the token hash
        count: Number of keys to generate (default: 256)
        session: Optional database session

    Returns:
        Number of keys created
    """

    def _create_pool(s: Session):
        token_hash = s.query(TokenHash).filter(TokenHash.id == token_hash_id).first()
        if not token_hash:
            raise ValueError(f"TokenHash with id {token_hash_id} not found")

        keypairs = generate_keypair_pool(count)

        ephemeral_keys = [
            ServerEphemeralKey(
                token_hash_id=token_hash_id,
                key_index=idx,
                private_key=private_key,
                public_key=public_key,
                used=False,
            )
            for idx, (private_key, public_key) in enumerate(keypairs)
        ]

        s.bulk_save_objects(ephemeral_keys)
        s.flush()
        return len(ephemeral_keys)

    if session:
        return _create_pool(session)

    with get_session() as s:
        return _create_pool(s)


def initialize_token_hash_with_keys(
    token_id: int, key_count: int = 256, session: Optional[Session] = None
) -> tuple[TokenHash, list]:
    """Create a new token hash and generate ephemeral key pool.

    Returns a tuple of (TokenHash, server_public_keys_list).

    Args:
        token_id: Token ID to link
        key_count: Number of ephemeral keys to generate
        session: Optional database session

    Returns:
        (TokenHash, [{"key_id": int, "public_key": bytes}, ...])
    """

    def _initialize(s: Session):
        token_hash = create_token_hash(token_id=token_id, session=s)
        create_ephemeral_key_pool(token_hash.id, key_count, session=s)
        s.refresh(token_hash)
        server_keys = [
            {"key_id": k.key_index, "public_key": k.public_key}
            for k in token_hash.server_keys.all()
        ]
        return token_hash, server_keys

    if session:
        return _initialize(session)

    with get_session() as s:
        token_hash, server_keys = _initialize(s)
        s.refresh(token_hash)
        return token_hash, server_keys
