# SPDX-License-Identifier: GPL-3.0-only
"""Adapter installs and updates run by the worker, with their output."""

import datetime
import uuid
from typing import cast

from sqlalchemy import CursorResult, Index, String, Text, Uuid, delete, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Mapped, Session, mapped_column

from publisher.db import Base
from publisher.db.types import UTCDateTime, utc_now
from publisher.errors import PublisherError

# Longer than the task's time limit, so only abandoned jobs are failed.
STALE_AFTER = datetime.timedelta(hours=1)
# Bytes, under MySQL's 65,535-byte TEXT limit.
LOG_LIMIT = 60 * 1024


class JobBusyError(PublisherError):
    pass


class PlatformAdapterJob(Base):
    __tablename__ = "platform_adapter_jobs"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    adapter_id: Mapped[str] = mapped_column(String(36))
    action: Mapped[str] = mapped_column(String(16))
    source_url: Mapped[str] = mapped_column(String(255))
    # The requested tag, then the one installed. NULL means the newest.
    tag: Mapped[str | None] = mapped_column(String(100), default=None)
    from_commit: Mapped[str | None] = mapped_column(String(40), default=None)
    to_commit: Mapped[str | None] = mapped_column(String(40), default=None)
    state: Mapped[str] = mapped_column(String(16), default="queued")
    # The adapter id while the job is active, NULL after. Being unique, it allows
    # one active job per adapter on every database.
    lock: Mapped[str | None] = mapped_column(String(36), default=None)
    log: Mapped[str] = mapped_column(Text, default="")
    requested_by: Mapped[uuid.UUID | None] = mapped_column(Uuid, default=None)
    created_at: Mapped[datetime.datetime] = mapped_column(UTCDateTime, default=utc_now)
    finished_at: Mapped[datetime.datetime | None] = mapped_column(
        UTCDateTime, default=None
    )

    __table_args__ = (
        Index("uq_platform_adapter_jobs_lock", "lock", unique=True),
        Index("ix_platform_adapter_jobs_adapter_id", "adapter_id", "created_at"),
    )


def create(
    session: Session,
    *,
    adapter_id: str,
    action: str,
    source_url: str,
    tag: str | None = None,
    from_commit: str | None = None,
    requested_by: uuid.UUID | None = None,
) -> PlatformAdapterJob:
    """Raises JobBusyError while another job for the adapter is active."""
    job = PlatformAdapterJob(
        adapter_id=adapter_id,
        action=action,
        source_url=source_url,
        tag=tag,
        from_commit=from_commit,
        lock=adapter_id,
        requested_by=requested_by,
    )
    session.add(job)
    try:
        session.flush()
    except IntegrityError:
        raise JobBusyError(
            "Another install or update of this adapter is running."
        ) from None
    return job


def start(session: Session, job_id: uuid.UUID) -> PlatformAdapterJob | None:
    """Mark a queued job running; None if it was already started or failed."""
    result = cast(
        CursorResult,
        session.execute(
            update(PlatformAdapterJob)
            .where(
                PlatformAdapterJob.id == job_id, PlatformAdapterJob.state == "queued"
            )
            .values(state="running")
            .execution_options(synchronize_session=False)
        ),
    )
    if result.rowcount != 1:
        return None
    return session.get(PlatformAdapterJob, job_id)


def finish(
    session: Session,
    job_id: uuid.UUID,
    *,
    state: str,
    log: list[str],
    tag: str | None = None,
    to_commit: str | None = None,
) -> None:
    job = session.get_one(PlatformAdapterJob, job_id)
    job.state = state
    # Cutting the bytes can split a character; the partial one is dropped.
    job.log = "\n".join(log).encode()[-LOG_LIMIT:].decode(errors="ignore")
    job.tag = tag or job.tag
    job.to_commit = to_commit
    job.lock = None
    job.finished_at = utc_now()


def list_for_adapter(
    session: Session, adapter_id: str, limit: int = 20
) -> list[PlatformAdapterJob]:
    return list(
        session.scalars(
            select(PlatformAdapterJob)
            .where(PlatformAdapterJob.adapter_id == adapter_id)
            .order_by(PlatformAdapterJob.created_at.desc())
            .limit(limit)
        )
    )


def fail_stale(session: Session) -> int:
    """Fail jobs a worker abandoned, e.g. by crashing, and free their adapters."""
    cutoff = utc_now() - STALE_AFTER
    result = cast(
        CursorResult,
        session.execute(
            update(PlatformAdapterJob)
            .where(
                PlatformAdapterJob.lock.is_not(None),
                PlatformAdapterJob.created_at < cutoff,
            )
            .values(
                state="failed",
                lock=None,
                finished_at=utc_now(),
                log=PlatformAdapterJob.log
                + "\nAbandoned: the worker never finished it.",
            )
            .execution_options(synchronize_session=False)
        ),
    )
    return result.rowcount


def delete_older_than(session: Session, cutoff: datetime.datetime) -> int:
    result = cast(
        CursorResult,
        session.execute(
            # By finish time, so a job failed just now as abandoned stays readable.
            delete(PlatformAdapterJob).where(PlatformAdapterJob.finished_at < cutoff)
        ),
    )
    return result.rowcount
