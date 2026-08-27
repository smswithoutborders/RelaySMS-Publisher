# SPDX-License-Identifier: GPL-3.0-only

import datetime

from celery.signals import worker_init

from db import get_session
from logutils import get_logger
from models.payload_session import delete_stale
from platforms.adapter_manager import AdapterManager
from tasks.celery_app import celery_app
from token_cleanup import cleanup_idle_tokens as run_idle_token_cleanup
from utils import get_configs

logger = get_logger(__name__)

PAYLOAD_SESSION_MAX_AGE_HOURS = int(
    get_configs("PAYLOAD_SESSION_MAX_AGE_HOURS", default_value="3")
)
TOKEN_IDLE_MAX_AGE_DAYS = int(
    get_configs("TOKEN_IDLE_MAX_AGE_DAYS", default_value="90")
)

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
    cutoff = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(
        hours=PAYLOAD_SESSION_MAX_AGE_HOURS
    )
    with get_session() as db:
        deleted = delete_stale(older_than=cutoff, session=db)

    if deleted:
        logger.info("Cleaned up %d stale payload session(s)", deleted)
    else:
        logger.debug("No stale payload sessions to clean up")


@celery_app.task(name="tasks.cleanup_task.cleanup_idle_tokens")
def cleanup_idle_tokens() -> None:
    """Delete tokens (and their keys) idle past the configured max age."""
    cutoff = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(
        days=TOKEN_IDLE_MAX_AGE_DAYS
    )
    with get_session() as db:
        counts = run_idle_token_cleanup(
            older_than=cutoff, session=db, adapter_manager=_get_adapter_manager()
        )

    if counts:
        logger.info("Cleaned up %d idle token(s): %s", sum(counts.values()), counts)
    else:
        logger.debug("No idle tokens to clean up")
