# SPDX-License-Identifier: GPL-3.0-only
"""Client ephemeral key model and related functions."""

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
from sqlalchemy.orm import relationship

from db import Base


def utc_now() -> datetime.datetime:
    return datetime.datetime.now(datetime.timezone.utc)


class ClientEphemeralKey(Base):
    """Client Ephemeral Key Model."""

    __tablename__ = "client_ephemeral_keys"

    id = Column(Integer, primary_key=True, autoincrement=True)
    token_hash_id = Column(
        Integer, ForeignKey("token_hashes.id", ondelete="CASCADE"), nullable=False
    )
    key_index = Column(Integer, nullable=False)
    public_key = Column(LargeBinary(32), nullable=False)
    used = Column(Boolean, default=False, nullable=False)
    created_at = Column(DateTime, default=utc_now, nullable=False)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now, nullable=False)
    used_at = Column(DateTime, nullable=True)

    token_hash = relationship("TokenHash", back_populates="client_keys")

    __table_args__ = (
        UniqueConstraint(
            "token_hash_id", "key_index", name="uq_client_keys_token_hash_id_key_index"
        ),
        Index("ix_client_ephemeral_keys_token_hash_id_used", "token_hash_id", "used"),
    )
