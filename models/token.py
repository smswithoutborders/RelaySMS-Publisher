# SPDX-License-Identifier: GPL-3.0-only
"""Token model and related functions."""

import datetime
import secrets
from typing import Any, Dict, Optional

from sqlalchemy import Column, DateTime, Integer, LargeBinary, String
from sqlalchemy.orm import Session

from db import Base, get_session
from db_types import EncryptedJSON


def utc_now() -> datetime.datetime:
    """Get current UTC datetime."""
    return datetime.datetime.now(datetime.timezone.utc)


def generate_token_id() -> bytes:
    """Generate random token ID."""
    return secrets.token_bytes(4)


class Token(Base):
    """Token Model.

    token_data: {"account_id": "...", "token": {...}}
    """

    __tablename__ = "tokens"

    id = Column(Integer, primary_key=True, autoincrement=True)
    token_id = Column(LargeBinary(4), nullable=False, unique=True)
    platform = Column(String(100), nullable=False, index=True)
    token_data = Column(EncryptedJSON(), nullable=False)
    created_at = Column(DateTime, default=utc_now, nullable=False)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now, nullable=False)


def create(
    platform: str, token_data: Dict[str, Any], session: Optional[Session] = None
) -> Token:
    """Create new token."""
    token = Token(
        token_id=generate_token_id(), platform=platform, token_data=token_data
    )

    if session:
        session.add(token)
        session.flush()
        return token

    with get_session() as s:
        s.add(token)
        s.flush()
        s.refresh(token)
        return token


def get_by_token_id(
    token_id: bytes, session: Optional[Session] = None
) -> Optional[Token]:
    """Get by token_id."""
    if session:
        return session.query(Token).filter(Token.token_id == token_id).first()

    with get_session() as s:
        return s.query(Token).filter(Token.token_id == token_id).first()


def get_by_id(token_id: int, session: Optional[Session] = None) -> Optional[Token]:
    """Get by ID."""
    if session:
        return session.query(Token).filter(Token.id == token_id).first()

    with get_session() as s:
        return s.query(Token).filter(Token.id == token_id).first()


def list_by_platform(platform: str, session: Optional[Session] = None) -> list[Token]:
    """List by platform."""
    if session:
        return session.query(Token).filter(Token.platform == platform).all()

    with get_session() as s:
        return s.query(Token).filter(Token.platform == platform).all()


def update(
    token_id: bytes,
    token_data: Optional[Dict[str, Any]] = None,
    session: Optional[Session] = None,
) -> int:
    """Update token data by token_id."""

    def _update(s: Session):
        if token_data is None:
            return 0

        return (
            s.query(Token)
            .filter(Token.token_id == token_id)
            .update({"token_data": token_data}, synchronize_session=False)
        )

    if session:
        rows = _update(session)
        session.flush()
        return rows

    with get_session() as s:
        return _update(s)


def delete(token_id: bytes, session: Optional[Session] = None) -> bool:
    """Delete by token_id."""

    def _delete(s: Session):
        token = s.query(Token).filter(Token.token_id == token_id).first()
        if not token:
            return False

        s.delete(token)
        s.flush()
        return True

    if session:
        return _delete(session)

    with get_session() as s:
        return _delete(s)
