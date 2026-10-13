# SPDX-License-Identifier: GPL-3.0-only

import logging

from celery.signals import worker_shutdown

from publisher import publications
from publisher.db import dispose_engine, get_session
from publisher.keys import KeyManagementError
from publisher.models.publication_stats import record as record_publication
from publisher.publications import (
    AdapterIntegrationError,
    OfflineTagError,
    PayloadMalformedError,
    PayloadNotSupportedError,
    ProtocolNotAllowedError,
)
from publisher.tasks.celery_app import celery_app

logger = logging.getLogger(__name__)

_FAILURE_REASON_MAX_LEN = 255


def _failure_reason(exc: Exception) -> str:
    return str(exc)[:_FAILURE_REASON_MAX_LEN]


@worker_shutdown.connect
def _on_worker_shutdown(**kwargs):
    dispose_engine()


@celery_app.task(name="tasks.publication_task.publish_message")
def publish_message(
    text_payload: str,
    sender_id: str,
    protocol: str | None = None,
    tag: str | None = None,
    country_code: str | None = None,
) -> None:
    """Validate and publish a payload, then record the outcome."""
    delivery = refreshed_token = None
    try:
        # Commits only after a successful send, so a failure leaves the payload's
        # keys usable, and a copy of it arriving meanwhile waits on their row lock.
        with get_session() as db:
            payload_raw, raw_segment, payload_type = publications.validate(text_payload)
            delivery = publications.prepare(
                db,
                payload_raw=payload_raw,
                sender_id=sender_id,
                raw_segment=raw_segment,
                payload_type=payload_type,
                protocol=protocol,
                tag=tag,
            )
            if delivery is None:
                # Incomplete multi-segment session, awaiting more parts.
                return
            new_token = publications.send(delivery)
            publications.finish(db, delivery, new_token)
            record_publication(
                db,
                protocol=protocol,
                status="published",
                platform_name=delivery.platform,
                country_code=country_code,
            )
            return
    except (
        PayloadMalformedError,
        PayloadNotSupportedError,
        ProtocolNotAllowedError,
        OfflineTagError,
        KeyManagementError,
    ) as exc:
        logger.error("Failed to process payload: %s", exc)
        platform_name, failure_reason = exc.platform_name, _failure_reason(exc)
    except AdapterIntegrationError as exc:
        logger.error("Failed to publish message: %s", exc)
        platform_name, failure_reason = exc.platform_name, _failure_reason(exc)
        refreshed_token = exc.token
    except Exception:
        logger.exception("An unexpected error occurred during task processing.")
        platform_name = delivery.platform if delivery else None
        failure_reason = "unexpected_error"

    with get_session() as db:
        if delivery and refreshed_token:
            publications.store_token(db, delivery, refreshed_token)
        record_publication(
            db,
            protocol=protocol,
            status="failed",
            platform_name=platform_name,
            country_code=country_code,
            failure_reason=failure_reason,
        )


def queue_publication(
    text_payload: str,
    address: str,
    protocol: str,
    *,
    tag: str | None = None,
    dialing_code: str | None = None,
) -> None:
    """Queue a payload under a keyed hash of the sender's address."""
    publish_message.delay(
        text_payload,
        publications.pseudonymize_sender(address),
        protocol,
        tag,
        publications.sender_country(address, dialing_code),
    )
