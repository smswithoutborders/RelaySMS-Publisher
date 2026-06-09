# SPDX-License-Identifier: GPL-3.0-only
"""Server ephemeral key model and related functions."""

import datetime
from typing import Optional

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    UniqueConstraint,
)
from sqlalchemy.orm import Session, relationship

from db import Base, get_session
from db_types import EncryptedBinary


def utc_now() -> datetime.datetime:
    """Get current UTC datetime."""
    return datetime.datetime.now(datetime.timezone.utc)


class ServerEphemeralKey(Base):
    """Server Ephemeral Key Model."""

    __tablename__ = "server_ephemeral_keys"

    id = Column(Integer, primary_key=True, autoincrement=True)
    token_hash_id = Column(
        Integer, ForeignKey("token_hashes.id", ondelete="CASCADE"), nullable=False
    )
    key_index = Column(Integer, nullable=False)
    private_key = Column(EncryptedBinary(), nullable=False)
    public_key = Column(LargeBinary(32), nullable=False)
    used = Column(Boolean, default=False, nullable=False)
    created_at = Column(DateTime, default=utc_now, nullable=False)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now, nullable=False)
    used_at = Column(DateTime, nullable=True)

    token_hash = relationship("TokenHash", back_populates="server_keys")

    __table_args__ = (
        UniqueConstraint(
            "token_hash_id", "key_index", name="uq_server_keys_token_hash_id_key_index"
        ),
        Index("ix_server_ephemeral_keys_token_hash_id_used", "token_hash_id", "used"),
    )


def mark_as_used(key_id: int, session: Optional[Session] = None) -> int:
    """Mark key as used."""

    def _update(s: Session):
        return (
            s.query(ServerEphemeralKey)
            .filter(ServerEphemeralKey.id == key_id)
            .update({"used": True, "used_at": utc_now()}, synchronize_session=False)
        )

    if session:
        rows = _update(session)
        session.flush()
        return rows

    with get_session() as s:
        return _update(s)


def get_by_index(
    token_hash_id: int, key_index: int, session: Optional[Session] = None
) -> Optional[ServerEphemeralKey]:
    """Get key by index."""
    if session:
        return (
            session.query(ServerEphemeralKey)
            .filter(
                ServerEphemeralKey.token_hash_id == token_hash_id,
                ServerEphemeralKey.key_index == key_index,
            )
            .first()
        )

    with get_session() as s:
        return (
            s.query(ServerEphemeralKey)
            .filter(
                ServerEphemeralKey.token_hash_id == token_hash_id,
                ServerEphemeralKey.key_index == key_index,
            )
            .first()
        )


def delete_all_for_token_hash(
    token_hash_id: int, session: Optional[Session] = None
) -> int:
    """Delete all keys for token hash."""

    def _delete(s: Session):
        return (
            s.query(ServerEphemeralKey)
            .filter(ServerEphemeralKey.token_hash_id == token_hash_id)
            .delete(synchronize_session=False)
        )

    if session:
        rows = _delete(session)
        session.flush()
        return rows

    with get_session() as s:
        return _delete(s)
