# SPDX-License-Identifier: GPL-3.0-only
"""Publication stats model and related functions."""

import datetime
from typing import Optional

from sqlalchemy import Index, String
from sqlalchemy.orm import Mapped, Session, mapped_column

from db import Base


def _utc_now() -> datetime.datetime:
    return datetime.datetime.now(datetime.timezone.utc)


class PublicationStats(Base):
    """One row per publish attempt outcome."""

    __tablename__ = "publication_stats"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    platform_name: Mapped[Optional[str]] = mapped_column(String(100), default=None)
    protocol: Mapped[Optional[str]] = mapped_column(String(20), default=None)
    status: Mapped[str] = mapped_column(String(20))
    country_code: Mapped[Optional[str]] = mapped_column(String(10), default=None)
    failure_reason: Mapped[Optional[str]] = mapped_column(String(255), default=None)
    created_at: Mapped[datetime.datetime] = mapped_column(default=_utc_now)

    __table_args__ = (
        Index("ix_publication_stats_created_at", "created_at"),
        Index("ix_publication_stats_status_created_at", "status", "created_at"),
    )


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
