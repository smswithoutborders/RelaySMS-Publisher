# SPDX-License-Identifier: GPL-3.0-only
"""TokenHash model and related functions."""

import datetime
import hashlib
import secrets
from typing import TYPE_CHECKING, List, Optional

from sqlalchemy import ForeignKey, LargeBinary
from sqlalchemy.orm import Mapped, Session, mapped_column, relationship

from db import Base

if TYPE_CHECKING:
    from models import ClientEphemeralKey, ServerEphemeralKey, Token


def utc_now() -> datetime.datetime:
    return datetime.datetime.now(datetime.timezone.utc)


class TokenHash(Base):
    """TokenHash Model."""

    __tablename__ = "token_hashes"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    token_hash: Mapped[bytes] = mapped_column(LargeBinary(32), unique=True)
    token_id: Mapped[int] = mapped_column(ForeignKey("tokens.id", ondelete="CASCADE"))
    created_at: Mapped[datetime.datetime] = mapped_column(default=utc_now)
    updated_at: Mapped[datetime.datetime] = mapped_column(
        default=utc_now, onupdate=utc_now
    )
    last_used_at: Mapped[Optional[datetime.datetime]] = mapped_column(default=None)

    token: Mapped["Token"] = relationship("Token", back_populates="token_hash")
    server_keys: Mapped[List["ServerEphemeralKey"]] = relationship(
        "ServerEphemeralKey", back_populates="token_hash", cascade="all, delete-orphan"
    )
    client_keys: Mapped[List["ClientEphemeralKey"]] = relationship(
        "ClientEphemeralKey", back_populates="token_hash", cascade="all, delete-orphan"
    )


def create(token_pk_id: int, session: Session) -> tuple[TokenHash, bytes]:
    """Create a new token hash."""
    raw_token = secrets.token_bytes(32)
    token_hash_bytes = hashlib.sha256(raw_token).digest()

    token_hash = TokenHash(token_hash=token_hash_bytes, token_id=token_pk_id)
    session.add(token_hash)
    session.flush()
    return token_hash, raw_token
