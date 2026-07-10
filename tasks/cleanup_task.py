# SPDX-License-Identifier: GPL-3.0-only

import datetime

from celery.utils.log import get_task_logger

from db import get_session
from models.payload_session import delete_stale
from tasks.celery_app import celery_app
from utils import get_configs

logger = get_task_logger(__name__)

PAYLOAD_SESSION_MAX_AGE_HOURS = int(
    get_configs("PAYLOAD_SESSION_MAX_AGE_HOURS", default_value="3")
)


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
