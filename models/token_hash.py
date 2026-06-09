# SPDX-License-Identifier: GPL-3.0-only
"""Token hash model and related functions."""

import datetime
import secrets
from typing import Optional

from sqlalchemy import Column, DateTime, ForeignKey, Integer, LargeBinary
from sqlalchemy.orm import Session, object_session, relationship

from db import Base, get_session


def utc_now() -> datetime.datetime:
    """Get current UTC datetime."""
    return datetime.datetime.now(datetime.timezone.utc)


class TokenHash(Base):
    """TokenHash Model."""

    __tablename__ = "token_hashes"

    id = Column(Integer, primary_key=True, autoincrement=True)
    token_hash = Column(LargeBinary(16), nullable=False, unique=True)
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

    def get_server_key_by_index(self, key_index: int):
        """Get server key by index."""
        from models.server_ephemeral_key import ServerEphemeralKey

        session = object_session(self)
        if session:
            return self.server_keys.filter(
                ServerEphemeralKey.key_index == key_index
            ).first()
        return None

    def get_client_key_by_index(self, key_index: int):
        """Get client key by index."""
        from models.client_ephemeral_key import ClientEphemeralKey

        session = object_session(self)
        if session:
            return self.client_keys.filter(
                ClientEphemeralKey.key_index == key_index
            ).first()
        return None

    def get_server_keys(self):
        """Get all server keys."""
        return self.server_keys.all()

    def get_client_keys(self):
        """Get all client keys."""
        return self.client_keys.all()

    def get_token(self):
        """Get associated token."""
        from models.token import Token

        session = object_session(self)
        if session:
            return session.query(Token).filter(Token.id == self.token_id).first()
        return None


def generate_token_hash() -> bytes:
    """Generate a random token hash."""
    return secrets.token_bytes(16)


def create(token_id: int, session: Optional[Session] = None) -> TokenHash:
    """Create new token hash."""
    token_hash = TokenHash(token_hash=generate_token_hash(), token_id=token_id)

    if session:
        session.add(token_hash)
        session.flush()
        return token_hash

    with get_session() as s:
        s.add(token_hash)
        s.flush()
        s.refresh(token_hash)
        return token_hash


def get_by_hash(
    token_hash: bytes, session: Optional[Session] = None
) -> Optional[TokenHash]:
    """Get by hash value."""
    if session:
        return (
            session.query(TokenHash).filter(TokenHash.token_hash == token_hash).first()
        )

    with get_session() as s:
        return s.query(TokenHash).filter(TokenHash.token_hash == token_hash).first()


def get_by_token_id(
    token_id: int, session: Optional[Session] = None
) -> Optional[TokenHash]:
    """Get by token ID."""
    if session:
        return session.query(TokenHash).filter(TokenHash.token_id == token_id).first()

    with get_session() as s:
        return s.query(TokenHash).filter(TokenHash.token_id == token_id).first()


def update_last_used(token_hash_id: int, session: Optional[Session] = None) -> int:
    """Update last_used_at. Returns rows updated."""

    def _update(s: Session):
        return (
            s.query(TokenHash)
            .filter(TokenHash.id == token_hash_id)
            .update({"last_used_at": utc_now()}, synchronize_session=False)
        )

    if session:
        rows = _update(session)
        session.flush()
        return rows

    with get_session() as s:
        return _update(s)


def delete(token_hash_id: int, session: Optional[Session] = None) -> bool:
    """Delete by ID."""

    def _delete(s: Session):
        token_hash = s.query(TokenHash).filter(TokenHash.id == token_hash_id).first()
        if not token_hash:
            return False

        s.delete(token_hash)
        s.flush()
        return True

    if session:
        return _delete(session)

    with get_session() as s:
        return _delete(s)
