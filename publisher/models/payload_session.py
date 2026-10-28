# SPDX-License-Identifier: GPL-3.0-only
"""Multi-part payloads waiting for all their segments."""

import datetime
from typing import TYPE_CHECKING

from sqlalchemy import String, UniqueConstraint, select
from sqlalchemy.exc import IntegrityError
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


def get_or_create_locked(
    session: Session, sender_id: str, session_id: int
) -> PayloadSession:
    """Return the payload session, locked until the transaction ends.

    Segments of one payload arrive together, so their workers take turns on this
    lock; otherwise each could miss the other's segment and none would join them.
    It inserts before locking: on MySQL, two workers locking a missing row deadlock.
    """
    try:
        with session.begin_nested():
            session.add(PayloadSession(sender_id=sender_id, session_id=session_id))
    except IntegrityError:
        pass  # Another worker created it first.
    return session.scalars(
        select(PayloadSession)
        .filter_by(sender_id=sender_id, session_id=session_id)
        .with_for_update()
    ).one()


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
