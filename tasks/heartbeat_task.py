# SPDX-License-Identifier: GPL-3.0-only

import requests

from logutils import get_logger
from tasks.celery_app import celery_app
from utils import get_configs

logger = get_logger(__name__)

WORKER_PUSH_URL = get_configs("UPTIME_KUMA_WORKER_PUSH_URL")


@celery_app.task(name="tasks.heartbeat_task.ping_worker_heartbeat")
def ping_worker_heartbeat() -> None:
    """Ping the Uptime Kuma push monitor. No-op if unconfigured."""
    if not WORKER_PUSH_URL:
        return

    try:
        requests.get(WORKER_PUSH_URL, timeout=5)
    except requests.RequestException as exc:
        logger.warning("Failed to ping worker heartbeat: %s", exc)
