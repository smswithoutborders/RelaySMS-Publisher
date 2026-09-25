# SPDX-License-Identifier: GPL-3.0-only
"""AdminSession model and related functions."""

import datetime
import hashlib
import hmac
import secrets
from typing import TYPE_CHECKING, Optional

from sqlalchemy import ForeignKey, Index, String, delete, func, or_, select
from sqlalchemy.orm import Mapped, Session, joinedload, mapped_column, relationship

import admin_auth_config
from db import Base
from db_types import UTCDateTime, utc_now

if TYPE_CHECKING:
    from models import AdminUser

# Limits last_seen_at writes to one per interval.
_TOUCH_INTERVAL = datetime.timedelta(seconds=60)
_CSRF_CONTEXT = b"relaysms-admin-csrf"


def _hash(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


def _expired_clause():
    now = utc_now()
    return or_(
        AdminSession.expires_at <= now,
        AdminSession.last_seen_at <= now - admin_auth_config.settings.idle_timeout,
    )


class AdminSession(Base):
    __tablename__ = "admin_sessions"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    admin_user_id: Mapped[int] = mapped_column(
        ForeignKey("admin_users.id", ondelete="CASCADE")
    )
    token_hash: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime.datetime] = mapped_column(UTCDateTime, default=utc_now)
    last_seen_at: Mapped[datetime.datetime] = mapped_column(
        UTCDateTime, default=utc_now
    )
    expires_at: Mapped[datetime.datetime] = mapped_column(UTCDateTime)
    user_agent: Mapped[Optional[str]] = mapped_column(String(255), default=None)

    admin_user: Mapped["AdminUser"] = relationship(
        "AdminUser", back_populates="sessions"
    )

    __table_args__ = (
        Index("uq_admin_sessions_token_hash", "token_hash", unique=True),
        Index("ix_admin_sessions_admin_user_id", "admin_user_id"),
        Index("ix_admin_sessions_expires_at", "expires_at"),
    )


def create(
    session: Session,
    admin_user: "AdminUser",
    *,
    max_age: datetime.timedelta,
    user_agent: Optional[str] = None,
) -> tuple[AdminSession, str]:
    raw_token = secrets.token_urlsafe(32)
    now = utc_now()

    admin_session = AdminSession(
        admin_user_id=admin_user.id,
        token_hash=_hash(raw_token),
        created_at=now,
        last_seen_at=now,
        expires_at=now + max_age,
        user_agent=user_agent[:255] if user_agent else None,
    )
    session.add(admin_session)
    session.flush()
    return admin_session, raw_token


def get_active(session: Session, raw_token: str) -> Optional[AdminSession]:
    admin_session = session.scalars(
        select(AdminSession)
        .options(joinedload(AdminSession.admin_user))
        .filter_by(token_hash=_hash(raw_token))
    ).first()
    if admin_session is None:
        return None

    now = utc_now()
    if admin_session.expires_at <= now:
        return None
    if admin_session.last_seen_at + admin_auth_config.settings.idle_timeout <= now:
        return None
    if not admin_session.admin_user.is_active:
        return None

    if now - admin_session.last_seen_at >= _TOUCH_INTERVAL:
        admin_session.last_seen_at = now
        session.flush()
    return admin_session


def csrf_token_for(raw_token: str) -> str:
    return hmac.new(raw_token.encode(), _CSRF_CONTEXT, hashlib.sha256).hexdigest()


def verify_csrf(raw_token: str, raw_csrf: Optional[str]) -> bool:
    if not raw_csrf:
        return False
    return hmac.compare_digest(csrf_token_for(raw_token), raw_csrf)


def revoke_all(session: Session, admin_user_id: int) -> int:
    result = session.execute(
        delete(AdminSession).where(AdminSession.admin_user_id == admin_user_id)
    )
    session.flush()
    return result.rowcount


def count_active_by_admin(session: Session) -> dict[int, int]:
    rows = session.execute(
        select(AdminSession.admin_user_id, func.count(AdminSession.id))
        .where(~_expired_clause())
        .group_by(AdminSession.admin_user_id)
    )
    return dict(rows.tuples().all())


def delete_expired(session: Session) -> int:
    result = session.execute(delete(AdminSession).where(_expired_clause()))
    session.flush()
    return result.rowcount
