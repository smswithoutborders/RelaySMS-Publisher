# SPDX-License-Identifier: GPL-3.0-only
"""Publication pipeline: assemble, decrypt and route payloads to adapters."""

import base64
import hmac
import logging
import secrets
import uuid
from collections.abc import Callable
from typing import Any

import magic
import phonenumbers
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from lib_relaysms_payload_specs.generated import relaysms_spec_payload as rrs
from publisher.config import DatabaseConfig, OfflinePublishConfig
from publisher.errors import PublisherError
from publisher.keys import pop_token_keys
from publisher.models import platform_adapter as platform_adapters
from publisher.models.payload_segment import create_if_not_exists as create_segment
from publisher.models.payload_segment import get_all_data
from publisher.models.payload_session import create as create_session
from publisher.models.payload_session import delete as delete_session
from publisher.models.payload_session import get_by_sender_and_session
from publisher.models.platform_adapter import OAUTH2, PNBA
from publisher.models.server_identity_key import get_private_key, mark_key_used
from publisher.models.token import update_token_data
from publisher.models.token_hash import update_last_used as mark_token_hash_used
from publisher.platforms import ipc

logger = logging.getLogger(__name__)

offline_config = OfflinePublishConfig.get()

OFFLINE_CONTENT_PLATFORM = "rmail"


class PublishContentRequest(BaseModel):
    """A payload as REST and SMTP receive it."""

    # Keeps the sender's address out of logged validation errors.
    model_config = ConfigDict(hide_input_in_errors=True)

    address: str = Field(
        ...,
        description="Sender ID from the gateway client, or an E.164 phone number",
        examples=["5447c1f50558292bd9df723f9fdc0b06b892199c7dcfaad5164f2d94dfd3470a"],
    )
    dialing_code: str | None = Field(
        None,
        pattern=r"^[1-9]\d{0,2}$",
        description="Sender's country calling code",
        examples=["237"],
    )
    text: str = Field(
        ...,
        description="Base64-encoded SMS payload",
    )


class PublicationError(PublisherError):
    pass


class PayloadMalformedError(PublicationError):
    pass


class PayloadNotSupportedError(PublicationError):
    pass


class AdapterIntegrationError(PublicationError):
    pass


class ProtocolNotAllowedError(PublicationError):
    pass


class OfflineTagError(PublicationError):
    pass


class OfflineTagMissingError(OfflineTagError):
    pass


class OfflineTagInvalidError(OfflineTagError):
    pass


def pseudonymize_sender(address: str) -> str:
    """Return a keyed hash of the sender's address."""
    key = hmac.digest(DatabaseConfig.get().data_encryption_key, b"sender-id", "sha256")
    return hmac.digest(key, address.encode(), "sha256").hex()


def sender_country(address: str, dialing_code: str | None = None) -> str | None:
    """Best-effort ISO region code from the dialing code or an E.164 address."""
    if dialing_code:
        region = phonenumbers.region_code_for_country_code(int(dialing_code))
        return None if region == phonenumbers.UNKNOWN_REGION else region
    try:
        return phonenumbers.region_code_for_number(phonenumbers.parse(address, None))
    except phonenumbers.NumberParseException:
        return None


def _recipient(content: rrs.V1ContentsContainer) -> str:
    to = content.get_to()
    if to is None:
        raise PayloadMalformedError("Content has no recipient.")
    return to.decode()


def validate(text_payload: str) -> tuple[bytes, bytes, rrs.V1PayloadsTypes]:
    """Verify base64 format and read the payload type."""
    try:
        payload_bytes = base64.b64decode(text_payload)
    except Exception as exc:
        logger.error("Failed to decode base64 payload: %s", exc)
        raise PayloadMalformedError("Payload is not valid base64.") from exc

    try:
        payload_type = rrs.v1_get_payload_type(payload_bytes)
    except Exception as exc:
        logger.exception("Failed to read payload type header.")
        raise PayloadMalformedError("Invalid payload structure.") from exc

    return payload_bytes, text_payload.encode(), payload_type


def publish(
    session: Session,
    payload_raw: bytes,
    sender_id: str,
    raw_segment: bytes,
    payload_type: rrs.V1PayloadsTypes,
    protocol: str | None = None,
    tag: str | None = None,
) -> str | None:
    """Publish a payload; return the platform, or None while segments are missing."""
    payload = _assemble(
        session,
        payload_raw=payload_raw,
        sender_id=sender_id,
        raw_segment=raw_segment,
        payload_type=payload_type,
    )

    if payload is None:
        return None

    return _dispatch(session, payload, protocol=protocol, tag=tag)


def _assemble(
    session: Session,
    payload_raw: bytes,
    sender_id: str,
    raw_segment: bytes,
    payload_type: rrs.V1PayloadsTypes,
) -> rrs.V1Payloads | None:
    match payload_type:
        case rrs.V1PayloadsTypes.WITHOUT_ATTACHMENT:
            try:
                return rrs.V1Payloads.deserialize_without_attachment(payload_raw)
            except Exception as exc:
                logger.exception("Failed to deserialize standalone payload.")
                raise PayloadMalformedError("Deserialization failed.") from exc

        case (
            rrs.V1PayloadsTypes.WITH_ATTACHMENT_HEADER
            | rrs.V1PayloadsTypes.WITH_ATTACHMENT_NO_HEADER
        ):
            return _store_segment_and_try_join(
                session,
                sender_id=sender_id,
                payload_raw=payload_raw,
                raw_segment=raw_segment,
            )

        case _:
            logger.error("Payload type not supported: %r", payload_type)
            raise PayloadNotSupportedError(f"Unsupported type: {payload_type!r}")


def _dispatch(
    session: Session,
    payload: rrs.V1Payloads,
    protocol: str | None = None,
    tag: str | None = None,
) -> str:
    token_id = payload.get_t_id()

    if token_id is None:
        if (
            offline_config.allowed_protocols
            and protocol not in offline_config.allowed_protocols
        ):
            logger.warning(
                "Discarding offline payload from disallowed protocol %r (allowed: %s).",
                protocol,
                offline_config.allowed_protocols,
            )
            raise ProtocolNotAllowedError(
                f"Protocol {protocol!r} is not allowed to publish offline content."
            )

        if protocol == "https" and offline_config.shared_secret:
            if not tag:
                logger.warning(
                    "Discarding offline payload with missing tag (protocol=%r).",
                    protocol,
                )
                raise OfflineTagMissingError(
                    "Tag is required for offline content over https."
                )

            if not secrets.compare_digest(
                tag.encode(), offline_config.shared_secret.encode()
            ):
                logger.warning(
                    "Discarding offline payload with invalid tag (protocol=%r).",
                    protocol,
                )
                raise OfflineTagInvalidError("Invalid tag for offline content.")

        return _publish_offline_content(
            session,
            key_id=payload.get_kid(),
            len_att=payload.get_len_att(),
            content_ciphertext=payload.get_content(),
        )

    return _publish_online_content(
        session,
        token_id=token_id,
        key_id=payload.get_kid(),
        len_att=payload.get_len_att(),
        content_ciphertext=payload.get_content(),
    )


def _publish_online_content(
    session: Session,
    token_id: int,
    key_id: int,
    len_att: int,
    content_ciphertext: bytes,
) -> str:
    token, token_hash_obj, ss_kid, es_kid, es_kid_pk, ec_kid_pk = pop_token_keys(
        session, token_id, key_id
    )

    try:
        content_bytes = rrs.v1_platform_publisher_decrypt(
            ec_kid_pk=ec_kid_pk,
            es_kid_pk=es_kid_pk,
            ss_kid=ss_kid,
            es_kid=es_kid,
            key_id=key_id,
            received_payload=content_ciphertext,
        )
    except Exception as exc:
        logger.exception(
            "Decryption failed for token %d with key %d.", token_id, key_id
        )
        raise PayloadMalformedError(
            "Online payload decryption failed.", platform_name=token.platform
        ) from exc

    mark_key_used(session, key_id)

    try:
        cat_id = rrs.v1_content_category_from_u8(token.cat_id)
    except Exception:
        logger.exception(
            "Unknown content category %r on token %d.", token.cat_id, token_id
        )
        raise

    try:
        content = rrs.V1ContentsContainer.deserialize(
            data=content_bytes, cat_id=cat_id, len_att=len_att
        )
    except Exception as exc:
        logger.exception("Failed to deserialize content for token %d.", token_id)
        raise PayloadMalformedError(
            "Online content deserialization failed.", platform_name=token.platform
        ) from exc

    try:
        proto_id = rrs.v1_payload_support_protocols_from_u8(token.proto_id)
    except Exception:
        logger.exception("Unknown protocol %r on token %d.", token.proto_id, token_id)
        raise

    account_id = token.token_data["account_id"]
    match proto_id:
        case rrs.V1PayloadsSupportedProtocols.O_AUTH20:
            adapter = platform_adapters.get_for_protocol(
                session, token.platform, OAUTH2
            )
            params = _get_adapter_params(
                content=content,
                extras={
                    "sender_id": account_id,
                    "from_email": account_id,
                    "token": token.token_data["token"],
                },
            )
        case rrs.V1PayloadsSupportedProtocols.PNBA:
            adapter = platform_adapters.get_for_protocol(session, token.platform, PNBA)
            params = _get_adapter_params(
                content=content,
                extras={
                    "phone_number": account_id,
                    "session": token.token_data["token"],
                    "base_path": adapter.state_path,
                },
            )
        case _:
            logger.error("Protocol %r not supported on token %d.", proto_id, token_id)
            raise PayloadNotSupportedError(
                f"Unsupported protocol: {proto_id!r}", platform_name=token.platform
            )

    pipe = ipc.invoke(
        adapter_path=adapter.path,
        venv_path=adapter.venv_path,
        method="send_message",
        params=params,
    )

    if pipe.get("error"):
        logger.error(
            "Adapter %r failed for token %d: %s",
            token.platform,
            token_id,
            pipe["error"],
        )
        raise AdapterIntegrationError(
            f"Adapter error: {pipe['error']}", platform_name=token.platform
        )

    result = pipe.get("result")
    if isinstance(result, bool):
        result = {"success": result}
    elif not isinstance(result, dict):
        result = {}

    # Refresh may have happened even if the send itself failed downstream
    # (e.g. token refreshed, then the HTTP call or attachment step failed).
    # Persist it regardless of outcome so the next attempt isn't stale.
    if proto_id == rrs.V1PayloadsSupportedProtocols.O_AUTH20:
        _maybe_refresh_token(session, token, result)
    elif proto_id == rrs.V1PayloadsSupportedProtocols.PNBA:
        _maybe_refresh_session(session, token, result)

    if not result.get("success", True):
        logger.error(
            "Adapter %r failed for token %d: %s",
            token.platform,
            token_id,
            result.get("message"),
        )
        raise AdapterIntegrationError(
            f"Adapter error: {result.get('message')}", platform_name=token.platform
        )

    mark_token_hash_used(session, token_hash_obj)
    logger.info("Published message for token %d via %r.", token_id, token.platform)
    return token.platform


def _maybe_refresh_token_data(
    session: Session,
    token,
    new_value: dict | None,
    *,
    label: str,
    compare_key: Callable[[dict], Any] = lambda v: v,
) -> None:
    new_key = compare_key(new_value or {})
    old_key = compare_key(token.token_data.get("token") or {})
    if new_key and new_key != old_key:
        update_token_data(session, token, {**token.token_data, "token": new_value})
        logger.info("Refreshed %s data for %r.", label, token.platform)


def _maybe_refresh_token(session: Session, token, result: dict) -> None:
    _maybe_refresh_token_data(
        session,
        token,
        result.get("refreshed_token"),
        label="OAuth token",
        compare_key=lambda v: (v or {}).get("refresh_token"),
    )


def _maybe_refresh_session(session: Session, token, result: dict) -> None:
    _maybe_refresh_token_data(
        session, token, result.get("refreshed_session"), label="PNBA session"
    )


def _publish_offline_content(
    session: Session,
    key_id: int,
    len_att: int,
    content_ciphertext: bytes,
) -> str:
    ss_kid = get_private_key(session, key_id).private_bytes_raw()

    try:
        offline_first = rrs.OfflineFirst.deserialize(content_ciphertext)
        content_obj = rrs.OfflineFirst.decrypt(ss=ss_kid, offline_first=offline_first)
    except Exception as exc:
        logger.exception("Failed to decrypt offline payload with key %d.", key_id)
        raise PayloadMalformedError(
            "Offline payload decryption failed.",
            platform_name=OFFLINE_CONTENT_PLATFORM,
        ) from exc

    mark_key_used(session, key_id)

    try:
        cat_id = rrs.V1ContentCategories.EMAIL
        content = rrs.V1ContentsContainer.deserialize(
            data=content_obj.get_payload(), cat_id=cat_id, len_att=len_att
        )
    except Exception as exc:
        logger.exception("Failed to deserialize offline content")
        raise PayloadMalformedError(
            "Offline content deserialization failed.",
            platform_name=OFFLINE_CONTENT_PLATFORM,
        ) from exc

    adapter = platform_adapters.get_for_protocol(
        session, OFFLINE_CONTENT_PLATFORM, PNBA
    )
    params = _get_adapter_params(
        content=content, extras={"base_path": adapter.state_path}
    )

    pipe = ipc.invoke(
        adapter_path=adapter.path,
        venv_path=adapter.venv_path,
        method="send_message",
        params=params,
    )

    if pipe.get("error"):
        logger.error("Adapter %r failed: %s", adapter.name, pipe["error"])
        raise AdapterIntegrationError(
            f"Adapter error: {pipe['error']}", platform_name=adapter.name
        )

    logger.info("Published offline content via %r.", adapter.name)
    return adapter.name


def _store_segment_and_try_join(
    session: Session, *, sender_id: str, payload_raw: bytes, raw_segment: bytes
) -> rrs.V1Payloads | None:
    sess_id = rrs.v1_get_payload_session_id(payload_raw)

    payload_session = get_by_sender_and_session(session, sender_id, sess_id)
    if payload_session is None:
        payload_session = create_session(session, sender_id, sess_id)

    create_segment(session, payload_session.id, raw_segment)
    segment_data = get_all_data(session, payload_session.id)

    try:
        joined = rrs.V1Payloads.join(segment_data)
    except Exception as exc:
        logger.warning(
            "Session %s not ready yet (%d segment(s) stored so far): %s: %s",
            sess_id,
            len(segment_data),
            type(exc).__name__,
            exc or "-",
        )
        return None

    delete_session(session, payload_session)
    logger.info("Session %s assembled from %d segments.", sess_id, len(segment_data))
    return joined


def _get_adapter_params(
    content: rrs.V1ContentsContainer, *, extras: dict | None = None
) -> dict:
    cat_id = content.get_cat_id()
    params = dict(extras) if extras else {}

    attachment = content.get_attachment()
    if attachment:
        try:
            mimetype = magic.from_buffer(attachment[:2048], mime=True)
        except magic.MagicException:
            mimetype = None

        if not mimetype:
            logger.warning("Could not determine MIME type of attachment.")
            mimetype = "application/octet-stream"

        extension = mimetype.split("/")[-1] or "bin"
        filename = f"{uuid.uuid4().hex}.{extension}"

        params["attachments"] = [
            {
                "data": base64.b64encode(attachment).decode(),
                "filename": filename,
                "mimetype": mimetype,
            }
        ]

    message = content.get_body().decode()

    match cat_id:
        case rrs.V1ContentCategories.TEXT:
            params["message"] = message

        case rrs.V1ContentCategories.MESSAGE:
            params["recipient"] = _recipient(content)
            params["message"] = message

        case rrs.V1ContentCategories.EMAIL:
            params["to_email"] = _recipient(content)
            params["subject"] = (content.get_subject() or b"").decode()
            params["message"] = message

        case _:
            logger.error("Content category not supported: %r", cat_id)
            raise PayloadNotSupportedError(f"Unsupported content category: {cat_id!r}")

    return params
