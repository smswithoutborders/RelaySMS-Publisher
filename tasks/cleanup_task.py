# SPDX-License-Identifier: GPL-3.0-only

from celery.signals import worker_init

from config import CleanupConfig
from db import get_session
from db_types import utc_now
from logutils import get_logger
from models.admin_session import delete_expired as delete_expired_admin_sessions
from models.payload_session import delete_stale
from platforms.adapter_manager import AdapterManager
from tasks.celery_app import celery_app
from token_cleanup import cleanup_idle_tokens as run_idle_token_cleanup

logger = get_logger(__name__)
cleanup_config = CleanupConfig.get()

_adapter_manager: AdapterManager | None = None


@worker_init.connect
def _on_worker_init(**kwargs):
    global _adapter_manager
    _adapter_manager = AdapterManager()


def _get_adapter_manager() -> AdapterManager:
    global _adapter_manager
    if _adapter_manager is None:
        _adapter_manager = AdapterManager()
    return _adapter_manager


@celery_app.task(name="tasks.cleanup_task.cleanup_stale_payload_sessions")
def cleanup_stale_payload_sessions() -> None:
    """Delete payload sessions left incomplete for longer than the max age."""
    cutoff = utc_now() - cleanup_config.payload_session_max_age
    with get_session() as db:
        deleted = delete_stale(older_than=cutoff, session=db)

    if deleted:
        logger.info("Cleaned up %d stale payload session(s)", deleted)
    else:
        logger.debug("No stale payload sessions to clean up")


@celery_app.task(name="tasks.cleanup_task.cleanup_idle_tokens")
def cleanup_idle_tokens() -> None:
    """Delete tokens (and their keys) idle past the configured max age."""
    cutoff = utc_now() - cleanup_config.token_idle_max_age
    with get_session() as db:
        counts = run_idle_token_cleanup(
            older_than=cutoff, session=db, adapter_manager=_get_adapter_manager()
        )

    if counts:
        logger.info("Cleaned up %d idle token(s): %s", sum(counts.values()), counts)
    else:
        logger.debug("No idle tokens to clean up")


@celery_app.task(name="tasks.cleanup_task.cleanup_expired_admin_sessions")
def cleanup_expired_admin_sessions() -> None:
    """Delete admin sessions past their expiry or idle timeout."""
    with get_session() as db:
        deleted = delete_expired_admin_sessions(db)

    if deleted:
        logger.info("Cleaned up %d expired admin session(s)", deleted)
    else:
        logger.debug("No expired admin sessions to clean up")
