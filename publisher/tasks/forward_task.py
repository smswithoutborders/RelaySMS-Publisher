# SPDX-License-Identifier: GPL-3.0-only

"""Fan out inbound Twilio SMS webhooks to additional configured URLs."""

import concurrent.futures
import logging
from datetime import UTC, datetime

import requests

from publisher.config import TwilioForwardConfig
from publisher.tasks.celery_app import celery_app

logger = logging.getLogger(__name__)
forward_config = TwilioForwardConfig.get()

_session = requests.Session()
_executor = concurrent.futures.ThreadPoolExecutor()


def _forward_one(url: str, **request_kwargs) -> None:
    try:
        _session.post(url, timeout=forward_config.timeout, **request_kwargs)
    except requests.RequestException:
        logger.exception("Failed to forward Twilio webhook to %s", url)


@celery_app.task(name="tasks.forward_task.forward_twilio_webhook")
def forward_twilio_webhook(
    raw_params: dict, sender_address: str, text_payload: str
) -> None:
    if not forward_config.urls_raw and not forward_config.urls_json:
        return

    normalized_payload = {
        "sender": sender_address,
        "text": text_payload,
        "received_at": datetime.now(UTC).isoformat(),
    }

    futures = [
        _executor.submit(_forward_one, url, data=raw_params)
        for url in forward_config.urls_raw
    ] + [
        _executor.submit(_forward_one, url, json=normalized_payload)
        for url in forward_config.urls_json
    ]
    concurrent.futures.wait(futures)
