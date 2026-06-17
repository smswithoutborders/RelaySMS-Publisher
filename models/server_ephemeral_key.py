# SPDX-License-Identifier: GPL-3.0-only
"""Server ephemeral key model and related functions."""

import datetime

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

from db import Base
from db_types import PrivateEncryptedBinary


def utc_now() -> datetime.datetime:
    return datetime.datetime.now(datetime.timezone.utc)


class ServerEphemeralKey(Base):
    """Server Ephemeral Key Model."""

    __tablename__ = "server_ephemeral_keys"

    id = Column(Integer, primary_key=True, autoincrement=True)
    token_hash_id = Column(
        Integer, ForeignKey("token_hashes.id", ondelete="CASCADE"), nullable=False
    )
    key_index = Column(Integer, nullable=False)
    private_key = Column(PrivateEncryptedBinary(), nullable=False)
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


def delete_by_index(token_hash_id: int, key_index: int, session: Session) -> None:
    """Delete a server ephemeral key by token_hash_id and key_index."""
    session.query(ServerEphemeralKey).filter_by(
        token_hash_id=token_hash_id, key_index=key_index
    ).delete()
