# SPDX-License-Identifier: GPL-3.0-only
"""Segments of multi-part payloads, kept until the payload is complete."""

import datetime
from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey, LargeBinary, select
from sqlalchemy.orm import Mapped, Session, mapped_column, relationship

from publisher.db import Base
from publisher.db.types import utc_now

if TYPE_CHECKING:
    from publisher.models import PayloadSession


class PayloadSegment(Base):
    __tablename__ = "payload_segments"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    session_id: Mapped[int] = mapped_column(
        ForeignKey("payload_sessions.id", ondelete="CASCADE")
    )
    data: Mapped[bytes] = mapped_column(LargeBinary)
    created_at: Mapped[datetime.datetime] = mapped_column(default=utc_now)
    updated_at: Mapped[datetime.datetime] = mapped_column(
        default=utc_now, onupdate=utc_now
    )

    session: Mapped["PayloadSession"] = relationship(
        "PayloadSession", back_populates="segments"
    )


def create(session: Session, session_id: int, data: bytes) -> None:
    session.add(PayloadSegment(session_id=session_id, data=data))
    session.flush()


def get_all_data(session: Session, session_id: int) -> list[bytes]:
    """Return the data of every segment stored for a payload session."""
    return list(
        session.scalars(
            select(PayloadSegment.data).where(PayloadSegment.session_id == session_id)
        )
    )
