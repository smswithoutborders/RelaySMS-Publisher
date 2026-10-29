# SPDX-License-Identifier: GPL-3.0-only

import logging

from celery.signals import worker_shutdown

from publisher import publications
from publisher.db import dispose_engine, get_session
from publisher.keys import (
    KeyManagementError,
    KeyNotFoundError,
    KeyUnavailableError,
    TokenVerificationError,
)
from publisher.models.publication_stats import record as record_publication
from publisher.publications import (
    AdapterIntegrationError,
    OfflineTagError,
    OfflineTagInvalidError,
    OfflineTagMissingError,
    PayloadMalformedError,
    PayloadNotSupportedError,
    ProtocolNotAllowedError,
)
from publisher.tasks.celery_app import celery_app
from relaysms_adapter_sdk.errors import (
    INTERNAL_ERROR,
    AuthenticationError,
    InvalidParamsError,
    RateLimitedError,
    TokenInvalidError,
    UpstreamError,
)

logger = logging.getLogger(__name__)

# Fixed failure codes for the stats. Error messages go only to the logs.
_FAILURE_REASONS = {
    PayloadMalformedError: "payload_malformed",
    PayloadNotSupportedError: "payload_not_supported",
    ProtocolNotAllowedError: "protocol_not_allowed",
    OfflineTagMissingError: "offline_tag_missing",
    OfflineTagInvalidError: "offline_tag_invalid",
    KeyNotFoundError: "token_not_found",
    KeyUnavailableError: "key_unavailable",
    TokenVerificationError: "token_verification_failed",
}
_ADAPTER_FAILURE_REASONS = {
    InvalidParamsError.code: "adapter_invalid_params",
    AuthenticationError.code: "adapter_auth_failed",
    TokenInvalidError.code: "adapter_token_invalid",
    RateLimitedError.code: "adapter_rate_limited",
    UpstreamError.code: "adapter_upstream",
    INTERNAL_ERROR: "adapter_internal",
}


def _failure_reason(exc: Exception) -> str:
    if isinstance(exc, AdapterIntegrationError):
        return _ADAPTER_FAILURE_REASONS.get(exc.code, "adapter_error")
    # A subclass of a mapped error gets its base class's code.
    for cls in type(exc).__mro__:
        if cls in _FAILURE_REASONS:
            return _FAILURE_REASONS[cls]
    return "unexpected_error"


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
    status = "failed"
    try:
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
            # Segments of a multi-part payload are still missing.
            return
        new_token = publications.send(delivery)
    except (ProtocolNotAllowedError, OfflineTagError) as exc:
        logger.warning("Rejected payload: %s", exc)
        status = "rejected"
        platform_name, failure_reason = exc.platform_name, _failure_reason(exc)
    except (PayloadMalformedError, PayloadNotSupportedError, KeyManagementError) as exc:
        logger.error("Failed to process payload: %s", exc)
        platform_name, failure_reason = exc.platform_name, _failure_reason(exc)
    except AdapterIntegrationError as exc:
        logger.error("Failed to publish message: %s", exc)
        platform_name, failure_reason = exc.platform_name, _failure_reason(exc)
        refreshed_token = exc.token
    except Exception as exc:
        logger.exception("An unexpected error occurred during task processing.")
        platform_name = delivery.platform if delivery else None
        failure_reason = _failure_reason(exc)
    else:
        try:
            with get_session() as db:
                publications.finish(db, delivery, new_token)
                record_publication(
                    db,
                    protocol=protocol,
                    status="published",
                    platform_name=delivery.platform,
                    country_code=country_code,
                )
        except Exception:
            logger.exception(
                "Sent via %r, but couldn't record the result.", delivery.platform
            )
        return

    with get_session() as db:
        if delivery and refreshed_token:
            publications.store_token(db, delivery, refreshed_token)
        record_publication(
            db,
            protocol=protocol,
            status=status,
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
