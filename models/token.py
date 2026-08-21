# SPDX-License-Identifier: GPL-3.0-only
"""Token model and related functions."""

import datetime
import secrets
from typing import TYPE_CHECKING, Any, Dict

from sqlalchemy import BigInteger, SmallInteger, String
from sqlalchemy.orm import Mapped, Session, mapped_column, relationship

from db import Base
from db_types import EncryptedJSON

if TYPE_CHECKING:
    from models import TokenHash


def _generate_uint32_token() -> int:
    return secrets.randbits(32)


def _utc_now() -> datetime.datetime:
    return datetime.datetime.now(datetime.timezone.utc)


class Token(Base):
    """Token Model.

    token_data: {"account_id": "...", "token": {...}}
    """

    __tablename__ = "tokens"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    token_id: Mapped[int] = mapped_column(
        BigInteger, default=_generate_uint32_token, unique=True
    )
    platform: Mapped[str] = mapped_column(String(100), index=True)
    cat_id: Mapped[int] = mapped_column(SmallInteger)
    proto_id: Mapped[int] = mapped_column(SmallInteger)
    token_data: Mapped[Dict[str, Any]] = mapped_column(EncryptedJSON)
    created_at: Mapped[datetime.datetime] = mapped_column(default=_utc_now)
    updated_at: Mapped[datetime.datetime] = mapped_column(
        default=_utc_now, onupdate=_utc_now
    )
    token_hash: Mapped["TokenHash"] = relationship(
        "TokenHash", back_populates="token", cascade="all, delete-orphan", uselist=False
    )


def create(
    platform: str,
    cat_id: int,
    proto_id: int,
    token_data: Dict[str, Any],
    session: Session,
) -> Token:
    """Create and persist a new token."""
    token = Token(
        platform=platform, cat_id=cat_id, proto_id=proto_id, token_data=token_data
    )
    session.add(token)
    session.flush()
    return token


def update_token_data(
    token: Token, new_token_data: dict[str, Any], session: Session
) -> Token:
    """Update the token_data of an existing token."""
    token.token_data = new_token_data
    session.flush()
    return token
