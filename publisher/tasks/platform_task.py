# SPDX-License-Identifier: GPL-3.0-only

import logging
import uuid

from publisher.db import get_session
from publisher.errors import PublisherError
from publisher.models import platform_adapter_job as jobs
from publisher.models.credential import Credential
from publisher.models.platform_adapter import PlatformAdapter
from publisher.platforms import manager
from publisher.tasks.celery_app import celery_app

logger = logging.getLogger(__name__)

# Under jobs.STALE_AFTER, so cleanup never fails a job that's still running.
TIME_LIMIT_SECONDS = 30 * 60


@celery_app.task(
    name="tasks.platform_task.run_adapter_job", time_limit=TIME_LIMIT_SECONDS
)
def run_adapter_job(job_id: str) -> None:
    """Install or update an adapter, then record the outcome on its job."""
    job_uuid = uuid.UUID(job_id)
    with get_session() as db:
        job = jobs.start(db, job_uuid)
        if job is None:
            return
        action, adapter_id, url, tag, requested_by = (
            job.action,
            job.adapter_id,
            job.source_url,
            job.tag,
            job.requested_by,
        )

    log: list[str] = []
    state, to_tag, to_commit = "failed", None, None
    try:
        with get_session() as db:
            actor = db.get(Credential, requested_by) if requested_by else None
            if action == "install":
                adapter = manager.install(db, url, tag, actor=actor, log=log)
            else:
                adapter = db.get(PlatformAdapter, adapter_id)
                if adapter is None:
                    raise manager.AdapterError("The adapter was removed.")
                manager.update(db, adapter, tag, actor=actor, log=log)
        manager.activate(adapter)
        state, to_tag, to_commit = "succeeded", adapter.tag, adapter.commit
    except PublisherError as e:
        log.append(f"Failed: {e}")
    except Exception as e:
        logger.exception("Adapter job %s failed unexpectedly", job_id)
        log.append(f"Failed unexpectedly: {e}")

    with get_session() as db:
        jobs.finish(db, job_uuid, state=state, log=log, tag=to_tag, to_commit=to_commit)
    logger.info("Adapter job %s %s %s: %s", job_id, action, adapter_id, state)
