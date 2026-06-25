# SPDX-License-Identifier: GPL-3.0-only
"""Payload segment model and related functions."""

import datetime
from typing import TYPE_CHECKING, List, Optional

from sqlalchemy import ForeignKey, LargeBinary, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Mapped, Session, mapped_column, relationship

from db import Base
from logutils import get_logger

if TYPE_CHECKING:
    from models import PayloadSession

logger = get_logger(__name__)


def _utc_now() -> datetime.datetime:
    return datetime.datetime.now(datetime.timezone.utc)


class PayloadSegment(Base):
    __tablename__ = "payload_segments"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    session_id: Mapped[int] = mapped_column(
        ForeignKey("payload_sessions.id", ondelete="CASCADE")
    )
    data: Mapped[bytes] = mapped_column(LargeBinary)
    created_at: Mapped[datetime.datetime] = mapped_column(default=_utc_now)
    updated_at: Mapped[datetime.datetime] = mapped_column(
        default=_utc_now, onupdate=_utc_now
    )

    session: Mapped["PayloadSession"] = relationship(
        "PayloadSession", back_populates="segments"
    )


def create_if_not_exists(
    session_id: int, data: bytes, session: Session
) -> Optional[PayloadSegment]:
    """Insert segment; silently returns None on duplicate without poisoning the session."""
    try:
        with session.begin_nested():
            seg = PayloadSegment(session_id=session_id, data=data)
            session.add(seg)
            session.flush()
            return seg
    except IntegrityError:
        logger.warning("duplicate segment for session_id=%d, ignoring", session_id)
        return None


def get_all_data(session_id: int, session: Session) -> List[bytes]:
    """Return all segment data bytes for a session as a flat list."""
    return list(
        session.scalars(
            select(PayloadSegment.data).where(PayloadSegment.session_id == session_id)
        )
    )
