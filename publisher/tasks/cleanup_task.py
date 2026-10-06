# SPDX-License-Identifier: GPL-3.0-only

import logging

from publisher.config import CleanupConfig
from publisher.db import get_session
from publisher.db.types import utc_now
from publisher.models import audit_event
from publisher.models import platform_adapter_job as adapter_jobs
from publisher.models.credential_session import (
    delete_expired as delete_expired_credential_sessions,
)
from publisher.models.payload_session import delete_stale
from publisher.tasks.celery_app import celery_app
from publisher.tokens import cleanup_idle_tokens as run_idle_token_cleanup

logger = logging.getLogger(__name__)
cleanup_config = CleanupConfig.get()


@celery_app.task(name="tasks.cleanup_task.cleanup_stale_payload_sessions")
def cleanup_stale_payload_sessions() -> None:
    """Delete payload sessions left incomplete for longer than the max age."""
    cutoff = utc_now() - cleanup_config.payload_session_max_age
    with get_session() as db:
        deleted = delete_stale(db, cutoff)

    if deleted:
        logger.info("Cleaned up %d stale payload session(s)", deleted)
    else:
        logger.debug("No stale payload sessions to clean up")


@celery_app.task(name="tasks.cleanup_task.cleanup_idle_tokens")
def cleanup_idle_tokens() -> None:
    """Delete tokens (and their keys) idle past the configured max age."""
    cutoff = utc_now() - cleanup_config.token_idle_max_age
    with get_session() as db:
        counts = run_idle_token_cleanup(db, cutoff)

    if counts:
        logger.info("Cleaned up %d idle token(s): %s", sum(counts.values()), counts)
    else:
        logger.debug("No idle tokens to clean up")


@celery_app.task(name="tasks.cleanup_task.cleanup_expired_credential_sessions")
def cleanup_expired_credential_sessions() -> None:
    """Delete credential sessions past their expiry or idle timeout."""
    with get_session() as db:
        deleted = delete_expired_credential_sessions(db)

    if deleted:
        logger.info("Cleaned up %d expired credential session(s)", deleted)
    else:
        logger.debug("No expired credential sessions to clean up")


@celery_app.task(name="tasks.cleanup_task.cleanup_old_audit_events")
def cleanup_old_audit_events() -> None:
    """Delete audit events older than the retention period."""
    cutoff = utc_now() - cleanup_config.audit_retention
    with get_session() as db:
        deleted = audit_event.delete_older_than(db, cutoff)

    if deleted:
        logger.info("Cleaned up %d old audit event(s)", deleted)
    else:
        logger.debug("No old audit events to clean up")


@celery_app.task(name="tasks.cleanup_task.cleanup_adapter_jobs")
def cleanup_adapter_jobs() -> None:
    """Fail abandoned adapter jobs and delete those past the audit retention."""
    with get_session() as db:
        failed = adapter_jobs.fail_stale(db)
        deleted = adapter_jobs.delete_older_than(
            db, utc_now() - cleanup_config.audit_retention
        )

    if failed or deleted:
        logger.info("Adapter jobs: %d abandoned, %d deleted", failed, deleted)
