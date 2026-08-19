# SPDX-License-Identifier: GPL-3.0-only

"""Fan out inbound Twilio SMS webhooks to additional configured URLs."""

import concurrent.futures
from datetime import datetime, timezone

import requests

from logutils import get_logger
from tasks.celery_app import celery_app
from utils import get_config_list, get_configs

logger = get_logger(__name__)

TWILIO_FORWARD_URLS_RAW = get_config_list("TWILIO_FORWARD_URLS_RAW")
TWILIO_FORWARD_URLS_JSON = get_config_list("TWILIO_FORWARD_URLS_JSON")
TWILIO_FORWARD_TIMEOUT = int(get_configs("TWILIO_FORWARD_TIMEOUT", default_value="10"))

_session = requests.Session()
_executor = concurrent.futures.ThreadPoolExecutor()


def _forward_one(url: str, **request_kwargs) -> None:
    try:
        _session.post(url, timeout=TWILIO_FORWARD_TIMEOUT, **request_kwargs)
    except requests.RequestException:
        logger.exception("Failed to forward Twilio webhook to %s", url)


@celery_app.task(name="tasks.forward_task.forward_twilio_webhook")
def forward_twilio_webhook(
    raw_params: dict, sender_address: str, text_payload: str
) -> None:
    """Relay an inbound Twilio SMS to any additionally configured URLs."""
    if not TWILIO_FORWARD_URLS_RAW and not TWILIO_FORWARD_URLS_JSON:
        return

    normalized_payload = {
        "sender": sender_address,
        "text": text_payload,
        "received_at": datetime.now(timezone.utc).isoformat(),
    }

    futures = [
        _executor.submit(_forward_one, url, data=raw_params)
        for url in TWILIO_FORWARD_URLS_RAW
    ] + [
        _executor.submit(_forward_one, url, json=normalized_payload)
        for url in TWILIO_FORWARD_URLS_JSON
    ]
    concurrent.futures.wait(futures)
