# SPDX-License-Identifier: GPL-3.0-only
"""Multi-part payloads waiting for all their segments."""

import datetime
from typing import TYPE_CHECKING

from sqlalchemy import String, UniqueConstraint, select
from sqlalchemy.orm import Mapped, Session, mapped_column, relationship

from publisher.db import Base
from publisher.db.types import utc_now

if TYPE_CHECKING:
    from publisher.models import PayloadSegment


class PayloadSession(Base):
    __tablename__ = "payload_sessions"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    sender_id: Mapped[str] = mapped_column(String(255))
    session_id: Mapped[int] = mapped_column()
    created_at: Mapped[datetime.datetime] = mapped_column(default=utc_now)
    updated_at: Mapped[datetime.datetime] = mapped_column(
        default=utc_now, onupdate=utc_now
    )

    segments: Mapped[list["PayloadSegment"]] = relationship(
        "PayloadSegment", back_populates="session", cascade="all, delete-orphan"
    )

    __table_args__ = (
        UniqueConstraint(
            "sender_id", "session_id", name="uq_session_sender_id_session_id"
        ),
    )


def create(session: Session, sender_id: str, session_id: int) -> PayloadSession:
    payload_session = PayloadSession(sender_id=sender_id, session_id=session_id)
    session.add(payload_session)
    session.flush()
    return payload_session


def get_by_sender_and_session(
    session: Session, sender_id: str, session_id: int
) -> PayloadSession | None:
    return session.scalar(
        select(PayloadSession).filter_by(sender_id=sender_id, session_id=session_id)
    )


def delete(session: Session, payload_session: PayloadSession) -> None:
    """Delete a payload session and its segments via cascade."""
    session.delete(payload_session)
    session.flush()


def delete_stale(session: Session, older_than: datetime.datetime) -> int:
    """Delete payload sessions created before the cutoff."""
    stale_sessions = session.scalars(
        select(PayloadSession).where(PayloadSession.created_at < older_than)
    ).all()
    for payload_session in stale_sessions:
        session.delete(payload_session)
    session.flush()
    return len(stale_sessions)
