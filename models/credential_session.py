# SPDX-License-Identifier: GPL-3.0-only
"""CredentialSession model and related functions."""

import datetime
import hashlib
import secrets
import uuid
from typing import TYPE_CHECKING, Optional

from sqlalchemy import ForeignKey, Index, String, delete, func, or_, select, update
from sqlalchemy.orm import Mapped, Session, joinedload, mapped_column, relationship

from config import AuthConfig
from db import Base
from db_types import UTCDateTime, utc_now

if TYPE_CHECKING:
    from models import Credential

# Limits last_seen_at writes to one per interval.
_TOUCH_INTERVAL = datetime.timedelta(seconds=60)


def _hash(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


def _expired_clause():
    now = utc_now()
    return or_(
        CredentialSession.expires_at <= now,
        CredentialSession.last_seen_at <= now - AuthConfig.get().idle_timeout,
    )


class CredentialSession(Base):
    __tablename__ = "credential_sessions"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    credential_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("credentials.id", ondelete="CASCADE")
    )
    token_hash: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime.datetime] = mapped_column(UTCDateTime, default=utc_now)
    last_seen_at: Mapped[datetime.datetime] = mapped_column(
        UTCDateTime, default=utc_now
    )
    expires_at: Mapped[datetime.datetime] = mapped_column(UTCDateTime)
    # Valid only while it matches the credential's.
    session_version: Mapped[int] = mapped_column()
    user_agent: Mapped[Optional[str]] = mapped_column(String(255), default=None)

    credential: Mapped["Credential"] = relationship(
        "Credential", back_populates="sessions"
    )

    __table_args__ = (
        Index("uq_credential_sessions_token_hash", "token_hash", unique=True),
        Index("ix_credential_sessions_credential_id", "credential_id"),
        Index("ix_credential_sessions_expires_at", "expires_at"),
    )


def create(
    session: Session,
    credential: "Credential",
    *,
    max_age: datetime.timedelta,
    user_agent: Optional[str] = None,
) -> tuple[CredentialSession, str]:
    raw_token = secrets.token_urlsafe(32)
    now = utc_now()

    credential_session = CredentialSession(
        credential_id=credential.id,
        token_hash=_hash(raw_token),
        created_at=now,
        last_seen_at=now,
        expires_at=now + max_age,
        session_version=credential.session_version,
        user_agent=user_agent[:255] if user_agent else None,
    )
    session.add(credential_session)
    session.flush()
    return credential_session, raw_token


def get_active(session: Session, raw_token: str) -> Optional[CredentialSession]:
    credential_session = session.scalars(
        select(CredentialSession)
        .options(joinedload(CredentialSession.credential))
        .filter_by(token_hash=_hash(raw_token))
        .where(~_expired_clause())
    ).first()
    if credential_session is None:
        return None

    credential = credential_session.credential
    # None if a login raced a delete, since sqlite doesn't enforce the foreign key.
    if credential is None or not credential.is_active:
        return None
    if credential_session.session_version != credential.session_version:
        return None

    now = utc_now()
    if now - credential_session.last_seen_at >= _TOUCH_INTERVAL:
        session.execute(
            update(CredentialSession)
            .where(CredentialSession.id == credential_session.id)
            .values(last_seen_at=now)
            .execution_options(synchronize_session=False)
        )
    return credential_session


def revoke_all(session: Session, credential_id: uuid.UUID) -> int:
    result = session.execute(
        delete(CredentialSession).where(
            CredentialSession.credential_id == credential_id
        )
    )
    session.flush()
    return result.rowcount


def count_active(session: Session, credential_id: uuid.UUID) -> int:
    return session.scalar(
        select(func.count(CredentialSession.id)).where(
            CredentialSession.credential_id == credential_id, ~_expired_clause()
        )
    )


def count_active_by_credential(session: Session) -> dict[uuid.UUID, int]:
    rows = session.execute(
        select(CredentialSession.credential_id, func.count(CredentialSession.id))
        .where(~_expired_clause())
        .group_by(CredentialSession.credential_id)
    )
    return dict(rows.tuples().all())


def delete_expired(session: Session) -> int:
    result = session.execute(delete(CredentialSession).where(_expired_clause()))
    session.flush()
    return result.rowcount
