# SPDX-License-Identifier: GPL-3.0-only
"""Outcomes of publish attempts, with listing and summaries."""

import datetime
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from sqlalchemy import Index, String, func, select
from sqlalchemy.orm import Mapped, Session, mapped_column

from publisher.db import Base, pagination
from publisher.db.pagination import Cursor, Page
from publisher.db.types import UTCDateTime, date_bucket, utc_now


class PublicationStats(Base):
    """One row per publish attempt outcome."""

    __tablename__ = "publication_stats"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    platform_name: Mapped[str | None] = mapped_column(String(100), default=None)
    protocol: Mapped[str | None] = mapped_column(String(20), default=None)
    status: Mapped[str] = mapped_column(String(20))
    country_code: Mapped[str | None] = mapped_column(String(10), default=None)
    failure_reason: Mapped[str | None] = mapped_column(String(255), default=None)
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
    protocol: str | None = None,
    platform_name: str | None = None,
    country_code: str | None = None,
    failure_reason: str | None = None,
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
class StatsFilters:
    status: str | None = None
    platform_name: str | None = None
    protocol: str | None = None
    country_code: str | None = None
    since: datetime.datetime | None = None
    until: datetime.datetime | None = None


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
    cursor: Cursor | None = None,
) -> Page[dict[str, Any]]:
    page = pagination.paginate(
        select(*LIST_COLUMNS).where(*_filter_clauses(filters)),
        PublicationStats.created_at,
        PublicationStats.id,
        limit=limit,
        cursor=cursor,
        fetch=lambda stmt: session.execute(stmt).all(),
    )
    return Page(
        items=[row._asdict() for row in page.items],
        next_cursor=page.next_cursor,
        prev_cursor=page.prev_cursor,
    )


def summarize(
    session: Session,
    *,
    group_by: Sequence[str],
    filters: StatsFilters,
    interval: str | None = None,
) -> list[dict[str, Any]]:
    unknown = [name for name in group_by if name not in GROUPABLE_COLUMNS]
    if unknown:
        raise ValueError(f"Unsupported group_by column(s): {', '.join(unknown)}")

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
