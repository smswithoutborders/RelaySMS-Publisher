# SPDX-License-Identifier: GPL-3.0-only

from celery.signals import worker_init, worker_shutdown
from celery.utils.log import get_task_logger

from db import dispose_engine, get_session
from keys import KeyManagerError
from platforms.adapter_manager import AdapterManager
from publications import (
    AdapterIntegrationError,
    PayloadMalformedError,
    PayloadNotSupportedError,
    ProtocolNotAllowedError,
    PublicationService,
)
from tasks.celery_app import celery_app

logger = get_task_logger(__name__)
_adapter_manager: AdapterManager | None = None


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
    try:
        payload_raw, raw_segment, payload_type = PublicationService.validate(
            text_payload
        )

        with get_session() as db:
            service = PublicationService(
                session=db, adapter_manager=_get_adapter_manager()
            )
            service.publish(
                payload_raw=payload_raw,
                sender_address=sender_address,
                raw_segment=raw_segment,
                payload_type=payload_type,
                protocol=protocol,
            )

    except (
        PayloadMalformedError,
        PayloadNotSupportedError,
        ProtocolNotAllowedError,
        KeyManagerError,
    ) as exc:
        logger.error("Failed to process payload: %s", exc)

    except AdapterIntegrationError as exc:
        logger.error("Failed to publish message: %s", exc)

    except Exception:
        logger.exception("An unexpected error occurred during task processing.")
