# SPDX-License-Identifier: GPL-3.0-only
"""Payload session model and related functions."""

import datetime
from typing import TYPE_CHECKING, List, Optional

from sqlalchemy import String, UniqueConstraint, select
from sqlalchemy.orm import Mapped, Session, mapped_column, relationship

from db import Base

if TYPE_CHECKING:
    from models import PayloadSegment


def _utc_now() -> datetime.datetime:
    return datetime.datetime.now(datetime.timezone.utc)


class PayloadSession(Base):
    __tablename__ = "payload_sessions"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    sender_id: Mapped[str] = mapped_column(String(255))
    session_id: Mapped[int] = mapped_column()
    created_at: Mapped[datetime.datetime] = mapped_column(default=_utc_now)
    updated_at: Mapped[datetime.datetime] = mapped_column(
        default=_utc_now, onupdate=_utc_now
    )

    segments: Mapped[List["PayloadSegment"]] = relationship(
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


def delete_stale(older_than: datetime.datetime, session: Session) -> int:
    """Delete payload sessions created before the cutoff."""
    stale_sessions = session.scalars(
        select(PayloadSession).where(PayloadSession.created_at < older_than)
    ).all()
    for payload_session in stale_sessions:
        session.delete(payload_session)
    session.flush()
    return len(stale_sessions)
