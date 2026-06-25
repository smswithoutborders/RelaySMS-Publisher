# SPDX-License-Identifier: GPL-3.0-only
"""Server identity key model and related functions."""

import base64
import datetime

from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey
from sqlalchemy import Column, DateTime, Integer, LargeBinary, select, update
from sqlalchemy.orm import Session

from db import Base, get_session
from db_types import PrivateEncryptedBinary


def utc_now() -> datetime.datetime:
    return datetime.datetime.now(datetime.timezone.utc)


class ServerIdentityKey(Base):
    """Persistent x25519 server identity key."""

    __tablename__ = "server_identity_keys"

    id = Column(Integer, primary_key=True, autoincrement=True)
    key_index = Column(Integer, nullable=False, unique=True)
    private_key = Column(PrivateEncryptedBinary(), nullable=False)
    public_key = Column(LargeBinary(32), nullable=False)
    created_at = Column(DateTime, default=utc_now, nullable=False)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now, nullable=False)
    last_used_at = Column(DateTime, nullable=True)
    used_count = Column(Integer, default=0, nullable=False)


def get_public_keys() -> list[dict]:
    """Get all public keys for API responses."""
    with get_session() as s:
        keys = s.scalars(
            select(ServerIdentityKey).order_by(ServerIdentityKey.key_index)
        ).all()
        return [
            {
                "key_id": key.key_index,
                "public_key": base64.urlsafe_b64encode(key.public_key).decode("ascii"),
            }
            for key in keys
        ]


def get_public_key(key_id: int) -> dict:
    """Get a single public key for API response."""
    if not (0 <= key_id <= 255):
        raise ValueError(f"Invalid key_id {key_id}: must be 0-255")
    with get_session() as s:
        key = s.scalar(
            select(ServerIdentityKey).where(ServerIdentityKey.key_index == key_id)
        )
        if not key:
            raise ValueError(f"Server identity key {key_id} not found")
        return {
            "key_id": key.key_index,
            "public_key": base64.urlsafe_b64encode(key.public_key).decode("ascii"),
        }


def get_private_key(key_id: int, session: Session) -> X25519PrivateKey:
    """Fetch a private key for cryptographic operations."""
    if not (0 <= key_id <= 255):
        raise ValueError(f"Invalid key_id {key_id}: must be 0-255")
    key = session.scalar(
        select(ServerIdentityKey).where(ServerIdentityKey.key_index == key_id)
    )
    if not key:
        raise ValueError(f"Server identity key {key_id} not found")
    return X25519PrivateKey.from_private_bytes(key.private_key)


def mark_key_used(key_id: int, session: Session) -> None:
    """Mark a server identity key as used after a successful operation."""
    if not (0 <= key_id <= 255):
        raise ValueError(f"Invalid key_id {key_id}: must be 0-255")
    result = session.execute(
        update(ServerIdentityKey)
        .where(ServerIdentityKey.key_index == key_id)
        .values(
            last_used_at=utc_now(),
            used_count=ServerIdentityKey.used_count + 1,
        )
    )
    if result.rowcount == 0:
        raise ValueError(f"Server identity key {key_id} not found")
