# SPDX-License-Identifier: GPL-3.0-only
"""Token model and related functions."""

import datetime
import secrets
from typing import Any, Optional

from sqlalchemy import (
    Column,
    DateTime,
    Integer,
    LargeBinary,
    SmallInteger,
    String,
    select,
)
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
    cat_id = Column(SmallInteger(), nullable=False)
    protocol = Column(String(100), nullable=False)
    token_data = Column(
        EncryptedJSON(), nullable=False
    )  # {"account_id": "...", "token": {...}}
    created_at = Column(DateTime, default=utc_now, nullable=False)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now, nullable=False)

    token_hash = relationship(
        "TokenHash", back_populates="token", cascade="all, delete-orphan", uselist=False
    )


def create(
    platform: str,
    cat_id: int,
    protocol: str,
    token_data: dict[str, Any],
    session: Session,
) -> Token:
    """Create and persist a new token."""
    token = Token(
        token_id=secrets.token_bytes(4),
        platform=platform,
        cat_id=cat_id,
        protocol=protocol,
        token_data=token_data,
    )
    session.add(token)
    session.flush()
    return token


def get_by_token_id(token_id: bytes, session: Session) -> Optional[Token]:
    """Fetch a token by its public token_id."""
    return session.scalar(select(Token).where(Token.token_id == token_id))


def update_token_data(
    token: Token, new_token_data: dict[str, Any], session: Session
) -> Token:
    """Update the token_data of an existing token."""
    token.token_data = new_token_data
    session.flush()
    return token
