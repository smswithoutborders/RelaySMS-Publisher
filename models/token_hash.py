# SPDX-License-Identifier: GPL-3.0-only
"""TokenHash model and related functions."""

import datetime
import hashlib
import secrets

from sqlalchemy import (
    Column,
    DateTime,
    ForeignKey,
    Integer,
    LargeBinary,
)
from sqlalchemy.orm import Session, relationship

from db import Base


def utc_now() -> datetime.datetime:
    return datetime.datetime.now(datetime.timezone.utc)


class TokenHash(Base):
    """TokenHash Model."""

    __tablename__ = "token_hashes"

    id = Column(Integer, primary_key=True, autoincrement=True)
    token_hash = Column(LargeBinary(32), nullable=False, unique=True)
    token_id = Column(
        Integer, ForeignKey("tokens.id", ondelete="CASCADE"), nullable=False
    )
    created_at = Column(DateTime, default=utc_now, nullable=False)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now, nullable=False)
    last_used_at = Column(DateTime, nullable=True)

    token = relationship("Token", back_populates="token_hash")
    server_keys = relationship(
        "ServerEphemeralKey", back_populates="token_hash", cascade="all, delete-orphan"
    )
    client_keys = relationship(
        "ClientEphemeralKey", back_populates="token_hash", cascade="all, delete-orphan"
    )


def create(token_id: int, session: Session) -> tuple[TokenHash, bytes]:
    """Create a new token hash."""
    raw_token = secrets.token_bytes(32)
    token_hash_bytes = hashlib.sha256(raw_token).digest()
    token_hash = TokenHash(token_hash=token_hash_bytes, token_id=token_id)
    session.add(token_hash)
    session.flush()
    return token_hash, raw_token
