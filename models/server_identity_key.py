# SPDX-License-Identifier: GPL-3.0-only
"""Server identity key model and related functions."""

import datetime
from typing import Optional

from sqlalchemy import Column, DateTime, Integer, LargeBinary
from sqlalchemy.orm import Session

from db import Base, get_session
from db_types import EncryptedBinary


def utc_now() -> datetime.datetime:
    """Get current UTC datetime."""
    return datetime.datetime.now(datetime.timezone.utc)


class ServerIdentityKey(Base):
    """Server Identity Key Model for persistent x25519 identity keys."""

    __tablename__ = "server_identity_keys"

    id = Column(Integer, primary_key=True, autoincrement=True)
    key_index = Column(Integer, nullable=False, unique=True)
    private_key = Column(EncryptedBinary(), nullable=False)
    public_key = Column(LargeBinary(32), nullable=False)
    created_at = Column(DateTime, default=utc_now, nullable=False)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now, nullable=False)
    last_used_at = Column(DateTime, nullable=True)
    used_count = Column(Integer, default=0, nullable=False)


def get_all_keys(session: Optional[Session] = None) -> list[ServerIdentityKey]:
    """Get all server identity keys ordered by key_index."""
    if session:
        return (
            session.query(ServerIdentityKey).order_by(ServerIdentityKey.key_index).all()
        )

    with get_session() as s:
        return s.query(ServerIdentityKey).order_by(ServerIdentityKey.key_index).all()


def get_key_by_index(
    key_index: int, session: Optional[Session] = None
) -> Optional[ServerIdentityKey]:
    """Get a single server identity key by index."""
    if session:
        return (
            session.query(ServerIdentityKey)
            .filter(ServerIdentityKey.key_index == key_index)
            .first()
        )

    with get_session() as s:
        return (
            s.query(ServerIdentityKey)
            .filter(ServerIdentityKey.key_index == key_index)
            .first()
        )


def mark_key_used(key_index: int, session: Optional[Session] = None) -> int:
    """Mark a key as used and increment usage counter."""

    def _update(s: Session):
        return (
            s.query(ServerIdentityKey)
            .filter(ServerIdentityKey.key_index == key_index)
            .update(
                {
                    "last_used_at": utc_now(),
                    "used_count": ServerIdentityKey.used_count + 1,
                },
                synchronize_session=False,
            )
        )

    if session:
        rows = _update(session)
        session.flush()
        return rows

    with get_session() as s:
        return _update(s)


def count_keys(session: Optional[Session] = None) -> int:
    """Count total number of server identity keys."""
    if session:
        return session.query(ServerIdentityKey).count()

    with get_session() as s:
        return s.query(ServerIdentityKey).count()


def get_public_keys() -> list[dict]:
    """Get all public keys for API responses.

    Returns:
        List of dicts with key_id and public_key (base64url encoded)
    """
    import base64

    with get_session() as s:
        keys = get_all_keys(session=s)
        return [
            {
                "key_id": key.key_index,
                "public_key": base64.urlsafe_b64encode(key.public_key).decode("ascii"),
            }
            for key in keys
        ]


def get_public_key(key_id: int) -> dict:
    """Get a single public key for API response.

    Args:
        key_id: Key index (0-255)

    Returns:
        Dict with key_id and public_key (base64url encoded)

    Raises:
        ValueError: If key_id is invalid or key not found
    """
    import base64

    if key_id < 0 or key_id > 255:
        raise ValueError(f"Invalid key_id: {key_id}. Must be 0-255.")

    with get_session() as s:
        key = get_key_by_index(key_id, session=s)
        if not key:
            raise ValueError(f"Server identity key with key_id {key_id} not found")

        return {
            "key_id": key.key_index,
            "public_key": base64.urlsafe_b64encode(key.public_key).decode("ascii"),
        }


def get_private_key(key_id: int):
    """Get private key object by key_id for cryptographic operations.

    Args:
        key_id: Key index (0-255)

    Returns:
        X25519PrivateKey object

    Raises:
        ValueError: If key_id is invalid or key not found
    """
    from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey

    if key_id < 0 or key_id > 255:
        raise ValueError(f"Invalid key_id: {key_id}. Must be 0-255.")

    with get_session() as s:
        key = get_key_by_index(key_id, session=s)
        if not key:
            raise ValueError(f"Server identity key with key_id {key_id} not found")

        mark_key_used(key_id, session=s)

        return X25519PrivateKey.from_private_bytes(key.private_key)
