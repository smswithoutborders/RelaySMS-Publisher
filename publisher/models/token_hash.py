# SPDX-License-Identifier: GPL-3.0-only
"""Hashes of the tokens issued to clients, used to verify them."""

import datetime
import hashlib
import secrets
from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey, Index, LargeBinary
from sqlalchemy.orm import Mapped, Session, mapped_column, relationship

from publisher.db import Base
from publisher.db.types import utc_now

if TYPE_CHECKING:
    from publisher.models import ClientEphemeralKey, ServerEphemeralKey, Token


class TokenHash(Base):
    __tablename__ = "token_hashes"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    token_hash: Mapped[bytes] = mapped_column(LargeBinary(32))
    token_id: Mapped[int] = mapped_column(ForeignKey("tokens.id", ondelete="CASCADE"))
    created_at: Mapped[datetime.datetime] = mapped_column(default=utc_now)
    updated_at: Mapped[datetime.datetime] = mapped_column(
        default=utc_now, onupdate=utc_now
    )
    last_used_at: Mapped[datetime.datetime | None] = mapped_column(default=None)

    token: Mapped["Token"] = relationship("Token", back_populates="token_hash")
    server_keys: Mapped[list["ServerEphemeralKey"]] = relationship(
        "ServerEphemeralKey", back_populates="token_hash", cascade="all, delete-orphan"
    )
    client_keys: Mapped[list["ClientEphemeralKey"]] = relationship(
        "ClientEphemeralKey", back_populates="token_hash", cascade="all, delete-orphan"
    )

    # MySQL can't index a BLOB/TEXT column without an explicit key length;
    # mysql_length is ignored on other dialects.
    __table_args__ = (
        Index(
            "uq_token_hashes_token_hash",
            "token_hash",
            unique=True,
            mysql_length=32,
        ),
        Index("ix_token_hashes_last_used_at", "last_used_at"),
    )


def create(session: Session, token_pk_id: int) -> tuple[TokenHash, bytes]:
    """Create a token hash; return it with the raw token, which isn't stored."""
    raw_token = secrets.token_bytes(32)
    token_hash_bytes = hashlib.sha256(raw_token).digest()

    token_hash = TokenHash(token_hash=token_hash_bytes, token_id=token_pk_id)
    session.add(token_hash)
    session.flush()
    return token_hash, raw_token


def update_last_used(session: Session, token_hash: TokenHash) -> None:
    token_hash.last_used_at = utc_now()
    session.add(token_hash)
    session.flush()
