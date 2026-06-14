# SPDX-License-Identifier: GPL-3.0-only
"""Token model and related functions."""

import datetime
import secrets
from typing import Any

import datetime
import secrets
from typing import Any, Optional

from sqlalchemy import Column, DateTime, Integer, LargeBinary, String
from sqlalchemy.orm import Session, relationship

from db import Base
from db_types import EncryptedJSON


def utc_now() -> datetime.datetime:
    return datetime.datetime.now(datetime.timezone.utc)


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

    token_hash = relationship(
        "TokenHash",
        back_populates="token",
        cascade="all, delete-orphan",
        uselist=False,
    )


def create(platform: str, token_data: dict[str, Any], session: Session) -> Token:
    """Create and persist a new token."""
    token = Token(
        token_id=secrets.token_bytes(4),
        platform=platform,
        token_data=token_data,
    )
    session.add(token)
    session.flush()
    return token


def get_by_token_id(token_id: bytes, session: Session) -> Optional[Token]:
    """Fetch a token by its public token_id."""
    return session.query(Token).filter(Token.token_id == token_id).first()
