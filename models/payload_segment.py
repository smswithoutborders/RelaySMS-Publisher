# SPDX-License-Identifier: GPL-3.0-only
"""Payload segment model and related functions."""

import datetime
from typing import Optional

from sqlalchemy import Column, DateTime, ForeignKey, Integer, LargeBinary, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, relationship

from db import Base
from logutils import get_logger

logger = get_logger(__name__)


def _utc_now() -> datetime.datetime:
    return datetime.datetime.now(datetime.timezone.utc)


class PayloadSegment(Base):
    __tablename__ = "payload_segments"

    id = Column(Integer, primary_key=True, autoincrement=True)
    session_id = Column(
        Integer, ForeignKey("payload_sessions.id", ondelete="CASCADE"), nullable=False
    )
    data = Column(LargeBinary, nullable=False)
    created_at = Column(DateTime, default=_utc_now, nullable=False)
    updated_at = Column(DateTime, default=_utc_now, onupdate=_utc_now, nullable=False)

    session = relationship("PayloadSession", back_populates="segments")


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


def get_all_data(session_id: int, session: Session) -> list[bytes]:
    """Return all segment data bytes for a session as a flat list."""
    return list(
        session.scalars(
            select(PayloadSegment.data).where(PayloadSegment.session_id == session_id)
        )
    )
