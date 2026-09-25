# SPDX-License-Identifier: GPL-3.0-only
"""Publication stats model and related functions."""

import base64
import binascii
import datetime
import json
import operator
from dataclasses import dataclass
from typing import Any, Literal, Optional, Sequence

from sqlalchemy import Index, String, and_, func, or_, select
from sqlalchemy.orm import Mapped, Session, mapped_column

from db import Base
from db_types import UTCDateTime, as_utc, date_bucket, utc_now

Direction = Literal["next", "prev"]
ADMIN_ONLY_COLUMNS = frozenset({"failure_reason"})
PUBLIC_SUMMARY_MAX_WINDOW = datetime.timedelta(days=366)


class InvalidCursorError(ValueError):
    pass


class SummaryWindowError(ValueError):
    pass


class AdminOnlyColumnError(PermissionError):
    pass


class PublicationStats(Base):
    """One row per publish attempt outcome."""

    __tablename__ = "publication_stats"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    platform_name: Mapped[Optional[str]] = mapped_column(String(100), default=None)
    protocol: Mapped[Optional[str]] = mapped_column(String(20), default=None)
    status: Mapped[str] = mapped_column(String(20))
    country_code: Mapped[Optional[str]] = mapped_column(String(10), default=None)
    failure_reason: Mapped[Optional[str]] = mapped_column(String(255), default=None)
    created_at: Mapped[datetime.datetime] = mapped_column(UTCDateTime, default=utc_now)

    # (created_at, id) serves keyset pagination; id breaks timestamp ties.
    __table_args__ = (
        Index("ix_publication_stats_created_at_id", "created_at", "id"),
        Index("ix_publication_stats_status_created_at", "status", "created_at"),
        Index(
            "ix_publication_stats_platform_name_created_at",
            "platform_name",
            "created_at",
        ),
        Index(
            "ix_publication_stats_country_code_created_at",
            "country_code",
            "created_at",
        ),
    )


LIST_COLUMNS = (
    PublicationStats.id,
    PublicationStats.platform_name,
    PublicationStats.protocol,
    PublicationStats.status,
    PublicationStats.country_code,
    PublicationStats.created_at,
    PublicationStats.failure_reason,
)

GROUPABLE_COLUMNS = {
    "status": PublicationStats.status,
    "platform_name": PublicationStats.platform_name,
    "protocol": PublicationStats.protocol,
    "country_code": PublicationStats.country_code,
    "failure_reason": PublicationStats.failure_reason,
}


def record(
    session: Session,
    *,
    status: str,
    protocol: Optional[str] = None,
    platform_name: Optional[str] = None,
    country_code: Optional[str] = None,
    failure_reason: Optional[str] = None,
) -> PublicationStats:
    """Record the outcome of a publish attempt."""
    stats = PublicationStats(
        protocol=protocol,
        status=status,
        platform_name=platform_name,
        country_code=country_code,
        failure_reason=failure_reason,
    )
    session.add(stats)
    session.flush()
    return stats


@dataclass(frozen=True)
class Cursor:
    created_at: datetime.datetime
    id: int
    direction: Direction


@dataclass(frozen=True)
class StatsFilters:
    status: Optional[str] = None
    platform_name: Optional[str] = None
    protocol: Optional[str] = None
    country_code: Optional[str] = None
    since: Optional[datetime.datetime] = None
    until: Optional[datetime.datetime] = None


@dataclass(frozen=True)
class StatsPage:
    data: list[dict[str, Any]]
    next_cursor: Optional[str]
    prev_cursor: Optional[str]


def encode_cursor(
    created_at: datetime.datetime, row_id: int, direction: Direction
) -> str:
    payload = json.dumps(
        {"t": as_utc(created_at).isoformat(), "i": row_id, "d": direction},
        separators=(",", ":"),
    )
    return base64.urlsafe_b64encode(payload.encode()).decode().rstrip("=")


def decode_cursor(cursor: str) -> Cursor:
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        data = json.loads(base64.urlsafe_b64decode(padded.encode()))
        created_at = as_utc(datetime.datetime.fromisoformat(data["t"]))
        row_id = data["i"]
        direction = data["d"]
    except (binascii.Error, UnicodeDecodeError, ValueError, KeyError, TypeError):
        raise InvalidCursorError("Invalid cursor.") from None

    if type(row_id) is not int or row_id < 1 or direction not in ("next", "prev"):
        raise InvalidCursorError("Invalid cursor.")
    return Cursor(created_at=created_at, id=row_id, direction=direction)


def _filter_clauses(filters: StatsFilters) -> list:
    clauses = []
    for name in ("status", "platform_name", "protocol", "country_code"):
        value = getattr(filters, name)
        if value is not None:
            clauses.append(getattr(PublicationStats, name) == value)
    if filters.since is not None:
        clauses.append(PublicationStats.created_at >= filters.since)
    if filters.until is not None:
        clauses.append(PublicationStats.created_at < filters.until)
    return clauses


def list_stats(
    session: Session,
    *,
    filters: StatsFilters,
    limit: int,
    cursor: Optional[Cursor] = None,
    is_admin: bool = False,
) -> StatsPage:
    columns = [c for c in LIST_COLUMNS if is_admin or c.key not in ADMIN_ONLY_COLUMNS]

    created_at, row_id = PublicationStats.created_at, PublicationStats.id
    backward = cursor is not None and cursor.direction == "prev"

    stmt = select(*columns).where(*_filter_clauses(filters))
    if cursor is not None:
        # OR form: row-value comparisons aren't consistent across databases.
        beyond = operator.gt if backward else operator.lt
        stmt = stmt.where(
            or_(
                beyond(created_at, cursor.created_at),
                and_(created_at == cursor.created_at, beyond(row_id, cursor.id)),
            )
        )

    order = (
        (created_at.asc(), row_id.asc())
        if backward
        else (created_at.desc(), row_id.desc())
    )
    rows = session.execute(stmt.order_by(*order).limit(limit + 1)).mappings().all()

    has_more = len(rows) > limit
    rows = rows[:limit]
    if backward:
        rows.reverse()

    if not rows:
        return StatsPage(data=[], next_cursor=None, prev_cursor=None)

    first, last = rows[0], rows[-1]
    if backward:
        has_next, has_prev = True, has_more
    else:
        has_next, has_prev = has_more, cursor is not None

    return StatsPage(
        data=[dict(row) for row in rows],
        next_cursor=(
            encode_cursor(last["created_at"], last["id"], "next") if has_next else None
        ),
        prev_cursor=(
            encode_cursor(first["created_at"], first["id"], "prev")
            if has_prev
            else None
        ),
    )


def summarize(
    session: Session,
    *,
    group_by: Sequence[str],
    filters: StatsFilters,
    interval: Optional[str] = None,
    is_admin: bool = False,
) -> list[dict[str, Any]]:
    unknown = [name for name in group_by if name not in GROUPABLE_COLUMNS]
    if unknown:
        raise ValueError(f"Unsupported group_by column(s): {', '.join(unknown)}")
    restricted = ADMIN_ONLY_COLUMNS.intersection(group_by)
    if restricted and not is_admin:
        raise AdminOnlyColumnError(
            f"Grouping by {', '.join(sorted(restricted))} requires authentication."
        )
    if not is_admin and filters.until - filters.since > PUBLIC_SUMMARY_MAX_WINDOW:
        raise SummaryWindowError(
            f"Window can't exceed {PUBLIC_SUMMARY_MAX_WINDOW.days} days "
            "without authentication."
        )

    columns = [GROUPABLE_COLUMNS[name].label(name) for name in group_by]
    count = func.count(PublicationStats.id).label("count")
    order_by = [count.desc(), *columns]
    if interval is not None:
        period = date_bucket(interval, PublicationStats.created_at).label("period")
        columns.insert(0, period)
        order_by.insert(0, period)
    stmt = (
        select(*columns, count)
        .where(*_filter_clauses(filters))
        .group_by(*columns)
        .order_by(*order_by)
    )
    return [dict(row) for row in session.execute(stmt).mappings().all()]
