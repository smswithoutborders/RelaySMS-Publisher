# SPDX-License-Identifier: GPL-3.0-only

import requests

from config import CeleryConfig
from logutils import get_logger
from tasks.celery_app import celery_app

logger = get_logger(__name__)
celery_config = CeleryConfig.get()


@celery_app.task(name="tasks.heartbeat_task.ping_worker_heartbeat")
def ping_worker_heartbeat() -> None:
    """Ping the Uptime Kuma push monitor. No-op if unconfigured."""
    url = celery_config.worker_heartbeat_url
    if not url:
        return

    try:
        requests.get(url, timeout=5)
    except requests.RequestException as exc:
        logger.warning("Failed to ping worker heartbeat: %s", exc)
