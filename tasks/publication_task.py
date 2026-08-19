# SPDX-License-Identifier: GPL-3.0-only

import phonenumbers
from celery.signals import worker_init, worker_shutdown

from db import dispose_engine, get_session
from keys import KeyManagerError
from logutils import get_logger
from models.publication_stats import record as record_publication
from platforms.adapter_manager import AdapterManager
from publications import (
    AdapterIntegrationError,
    PayloadMalformedError,
    PayloadNotSupportedError,
    ProtocolNotAllowedError,
    PublicationService,
)
from tasks.celery_app import celery_app

logger = get_logger(__name__)
_adapter_manager: AdapterManager | None = None

_FAILURE_REASON_MAX_LEN = 255


def _failure_reason(exc: Exception) -> str:
    return str(exc)[:_FAILURE_REASON_MAX_LEN]


def _derive_country_code(sender_address: str) -> str | None:
    """Best-effort ISO region code for a sender's phone number."""
    try:
        return phonenumbers.region_code_for_number(
            phonenumbers.parse(sender_address, None)
        )
    except phonenumbers.NumberParseException:
        return None


@worker_init.connect
def _on_worker_init(**kwargs):
    global _adapter_manager
    _adapter_manager = AdapterManager()


@worker_shutdown.connect
def _on_worker_shutdown(**kwargs):
    dispose_engine()


def _get_adapter_manager() -> AdapterManager:
    global _adapter_manager
    if _adapter_manager is None:
        _adapter_manager = AdapterManager()
    return _adapter_manager


@celery_app.task(name="tasks.publication_task.publish_message")
def publish_message(
    text_payload: str, sender_address: str, protocol: str | None = None
) -> None:
    """Validate, assemble, and run message publication pipeline."""
    with get_session() as db:
        try:
            payload_raw, raw_segment, payload_type = PublicationService.validate(
                text_payload
            )

            service = PublicationService(
                session=db, adapter_manager=_get_adapter_manager()
            )
            platform_name = service.publish(
                payload_raw=payload_raw,
                sender_address=sender_address,
                raw_segment=raw_segment,
                payload_type=payload_type,
                protocol=protocol,
            )

            if platform_name is None:
                # Incomplete multi-segment session, awaiting more parts.
                return

            record_publication(
                db,
                protocol=protocol,
                status="published",
                platform_name=platform_name,
                country_code=_derive_country_code(sender_address),
            )

        except (
            PayloadMalformedError,
            PayloadNotSupportedError,
            ProtocolNotAllowedError,
            KeyManagerError,
        ) as exc:
            record_publication(
                db,
                protocol=protocol,
                status="failed",
                country_code=_derive_country_code(sender_address),
                failure_reason=_failure_reason(exc),
            )
            logger.error("Failed to process payload: %s", exc)

        except AdapterIntegrationError as exc:
            record_publication(
                db,
                protocol=protocol,
                status="failed",
                country_code=_derive_country_code(sender_address),
                failure_reason=_failure_reason(exc),
            )
            logger.error("Failed to publish message: %s", exc)

        except Exception:
            record_publication(
                db,
                protocol=protocol,
                status="failed",
                country_code=_derive_country_code(sender_address),
                failure_reason="unexpected_error",
            )
            logger.exception("An unexpected error occurred during task processing.")
