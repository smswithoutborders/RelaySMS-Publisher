# SPDX-License-Identifier: GPL-3.0-only
"""Who did what to credentials, kept for review."""

import datetime
import uuid
from collections.abc import Iterable
from enum import StrEnum
from typing import Any, cast

from sqlalchemy import JSON, CursorResult, Index, String, Uuid, delete, or_, select
from sqlalchemy.orm import Mapped, Session, mapped_column

from publisher.db import Base, pagination
from publisher.db.pagination import Cursor, Page
from publisher.db.types import UTCDateTime, utc_now
from publisher.models.credential import MAX_USERNAME_LENGTH, Credential, Scope


class AuditAction(StrEnum):
    """Named <area>.<verb>. Reading an area's events needs its scope in AREA_SCOPES."""

    AUTH_LOGIN = "auth.login"
    AUTH_LOGOUT = "auth.logout"
    CREDS_CREATE = "creds.create"
    CREDS_UPDATE = "creds.update"
    CREDS_RESET_PASSWORD = "creds.reset_password"
    CREDS_REVOKE_SESSIONS = "creds.revoke_sessions"
    CREDS_DELETE = "creds.delete"


class AuditOutcome(StrEnum):
    SUCCESS = "success"
    # The change went beyond the actor's scopes.
    DENIED = "denied"
    # A login refused for an existing username: wrong password or disabled.
    FAILED = "failed"


AREA_SCOPES = {
    "auth": Scope.CREDS_READ,
    "creds": Scope.CREDS_READ,
}


class AuditEvent(Base):
    __tablename__ = "audit_events"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    occurred_at: Mapped[datetime.datetime] = mapped_column(UTCDateTime, default=utc_now)
    # NULL when no credential acted: the CLI, or a failed login.
    actor_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, default=None)
    # The usernames are copied so events still read right after a deletion.
    actor_username: Mapped[str | None] = mapped_column(
        String(MAX_USERNAME_LENGTH), default=None
    )
    # Plain strings, so adding an action needs no migration and old ones still list.
    action: Mapped[str] = mapped_column(String(64))
    target_id: Mapped[str | None] = mapped_column(String(64), default=None)
    target_label: Mapped[str | None] = mapped_column(String(255), default=None)
    outcome: Mapped[str] = mapped_column(String(16))
    # What changed. Never secrets.
    details: Mapped[dict[str, Any] | None] = mapped_column(JSON, default=None)

    __table_args__ = (Index("ix_audit_events_occurred_at_id", "occurred_at", "id"),)


def record(
    session: Session,
    action: AuditAction,
    *,
    actor: Credential | None,
    target: Credential | None = None,
    outcome: AuditOutcome = AuditOutcome.SUCCESS,
    details: dict[str, Any] | None = None,
) -> None:
    session.add(
        AuditEvent(
            actor_id=actor.id if actor else None,
            actor_username=actor.username if actor else None,
            action=action,
            target_id=str(target.id) if target else None,
            target_label=target.username if target else None,
            outcome=outcome,
            details=details,
        )
    )


def list_events(
    session: Session,
    *,
    scopes: Iterable[Scope],
    limit: int,
    cursor: Cursor | None = None,
    action: AuditAction | None = None,
    actor: str | None = None,
    target: str | None = None,
    since: datetime.datetime | None = None,
    until: datetime.datetime | None = None,
) -> Page[AuditEvent]:
    """Newest first, only from the areas whose scope is in scopes."""
    areas = [area for area, scope in AREA_SCOPES.items() if scope in scopes]
    if not areas:
        return Page(items=[], next_cursor=None, prev_cursor=None)

    stmt = select(AuditEvent).where(
        or_(*(AuditEvent.action.startswith(f"{area}.") for area in areas))
    )
    if action is not None:
        stmt = stmt.where(AuditEvent.action == action)
    if actor is not None:
        stmt = stmt.where(AuditEvent.actor_username == actor)
    if target is not None:
        stmt = stmt.where(AuditEvent.target_label == target)
    if since is not None:
        stmt = stmt.where(AuditEvent.occurred_at >= since)
    if until is not None:
        stmt = stmt.where(AuditEvent.occurred_at < until)

    return pagination.paginate(
        stmt,
        AuditEvent.occurred_at,
        AuditEvent.id,
        limit=limit,
        cursor=cursor,
        fetch=lambda stmt: session.scalars(stmt).all(),
    )


def delete_older_than(session: Session, cutoff: datetime.datetime) -> int:
    result = cast(
        CursorResult,
        session.execute(delete(AuditEvent).where(AuditEvent.occurred_at < cutoff)),
    )
    return result.rowcount
