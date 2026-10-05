# SPDX-License-Identifier: GPL-3.0-only
"""Client ephemeral key model and related functions."""

import datetime
from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey, Index, LargeBinary, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from publisher.db import Base
from publisher.db.types import utc_now

if TYPE_CHECKING:
    from publisher.models import TokenHash


class ClientEphemeralKey(Base):
    """Client Ephemeral Key Model."""

    __tablename__ = "client_ephemeral_keys"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    token_hash_id: Mapped[int] = mapped_column(
        ForeignKey("token_hashes.id", ondelete="CASCADE")
    )
    key_index: Mapped[int] = mapped_column()
    public_key: Mapped[bytes] = mapped_column(LargeBinary(32))
    used: Mapped[bool] = mapped_column(default=False)
    created_at: Mapped[datetime.datetime] = mapped_column(default=utc_now)
    updated_at: Mapped[datetime.datetime] = mapped_column(
        default=utc_now, onupdate=utc_now
    )
    used_at: Mapped[datetime.datetime | None] = mapped_column(default=None)

    token_hash: Mapped[TokenHash] = relationship(
        "TokenHash", back_populates="client_keys"
    )

    __table_args__ = (
        UniqueConstraint(
            "token_hash_id", "key_index", name="uq_client_keys_token_hash_id_key_index"
        ),
        Index("ix_client_ephemeral_keys_token_hash_id_used", "token_hash_id", "used"),
    )
