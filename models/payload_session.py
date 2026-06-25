# SPDX-License-Identifier: GPL-3.0-only
"""Payload session model and related functions."""

import datetime
from typing import Optional

from sqlalchemy import Column, DateTime, Integer, String, UniqueConstraint, select
from sqlalchemy.orm import Session, relationship

from db import Base


def _utc_now() -> datetime.datetime:
    return datetime.datetime.now(datetime.timezone.utc)


class PayloadSession(Base):
    __tablename__ = "payload_sessions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    sender_id = Column(String, nullable=False)
    session_id = Column(Integer, nullable=False)
    created_at = Column(DateTime, default=_utc_now, nullable=False)
    updated_at = Column(DateTime, default=_utc_now, onupdate=_utc_now, nullable=False)

    segments = relationship(
        "PayloadSegment", back_populates="session", cascade="all, delete-orphan"
    )

    __table_args__ = (
        UniqueConstraint(
            "sender_id", "session_id", name="uq_session_sender_id_session_id"
        ),
    )


def create(sender_id: str, session_id: int, session: Session) -> PayloadSession:
    """Create and persist a new payload session."""
    payload_session = PayloadSession(sender_id=sender_id, session_id=session_id)
    session.add(payload_session)
    session.flush()
    return payload_session


def get_by_sender_and_session(
    sender_id: str, session_id: int, session: Session
) -> Optional[PayloadSession]:
    """Retrieve a payload session by sender_id and session_id."""
    return session.scalar(
        select(PayloadSession).filter_by(sender_id=sender_id, session_id=session_id)
    )


def delete(payload_session: PayloadSession, session: Session) -> None:
    """Delete a payload session and its segments via cascade."""
    session.delete(payload_session)
    session.flush()
