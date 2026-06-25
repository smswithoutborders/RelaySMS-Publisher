# SPDX-License-Identifier: GPL-3.0-only
"""Server identity key model and related functions."""

import base64
import datetime
from typing import Any, Dict, List, Optional

from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey
from sqlalchemy import LargeBinary, select, update
from sqlalchemy.orm import Mapped, Session, mapped_column

from db import Base, get_session
from db_types import PrivateEncryptedBinary


def _utc_now() -> datetime.datetime:
    return datetime.datetime.now(datetime.timezone.utc)


class ServerIdentityKey(Base):
    """Persistent x25519 server identity key."""

    __tablename__ = "server_identity_keys"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    key_index: Mapped[int] = mapped_column(unique=True)
    private_key: Mapped[bytes] = mapped_column(PrivateEncryptedBinary)
    public_key: Mapped[bytes] = mapped_column(LargeBinary(32))
    created_at: Mapped[datetime.datetime] = mapped_column(default=_utc_now)
    updated_at: Mapped[datetime.datetime] = mapped_column(
        default=_utc_now, onupdate=_utc_now
    )
    last_used_at: Mapped[Optional[datetime.datetime]] = mapped_column(default=None)
    used_count: Mapped[int] = mapped_column(default=0)


def get_public_keys() -> List[Dict[str, Any]]:
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


def get_public_key(key_id: int) -> Dict[str, Any]:
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
