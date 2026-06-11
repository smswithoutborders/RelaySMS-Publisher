# SPDX-License-Identifier: GPL-3.0-only
"""TokenHash model and related functions."""

import datetime
import secrets
from typing import Optional

from sqlalchemy import Column, DateTime, ForeignKey, Integer, LargeBinary
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

    server_keys = relationship(
        "ServerEphemeralKey",
        back_populates="token_hash",
        cascade="all, delete-orphan",
        lazy="dynamic",
    )
    client_keys = relationship(
        "ClientEphemeralKey",
        back_populates="token_hash",
        cascade="all, delete-orphan",
        lazy="dynamic",
    )


def create(token_id: int, session: Session) -> tuple[TokenHash, bytes]:
    """Create a new token hash."""
    import hashlib

    raw_token = secrets.token_bytes(32)
    token_hash_bytes = hashlib.sha256(raw_token).digest()
    token_hash = TokenHash(token_hash=token_hash_bytes, token_id=token_id)
    session.add(token_hash)
    session.flush()
    return token_hash, raw_token


def get_by_hash(token_hash: bytes, session: Session) -> Optional[TokenHash]:
    """Get by hash value."""
    return session.query(TokenHash).filter(TokenHash.token_hash == token_hash).first()


def get_by_token_id(token_id: int, session: Session) -> Optional[TokenHash]:
    """Get by token ID."""
    return session.query(TokenHash).filter(TokenHash.token_id == token_id).first()


def update_last_used(token_hash_id: int, session: Session) -> int:
    """Update last_used_at. Returns rows updated."""
    return (
        session.query(TokenHash)
        .filter(TokenHash.id == token_hash_id)
        .update({"last_used_at": utc_now()}, synchronize_session=False)
    )


def delete(token_hash_id: int, session: Session) -> bool:
    """Delete by ID. Returns True if deleted."""
    token_hash = session.query(TokenHash).filter(TokenHash.id == token_hash_id).first()
    if not token_hash:
        return False
    session.delete(token_hash)
    return True
