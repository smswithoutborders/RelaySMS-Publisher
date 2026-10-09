# SPDX-License-Identifier: GPL-3.0-only
"""Publication pipeline: assemble, decrypt and route payloads to adapters."""

import base64
import hmac
import logging
import secrets
import uuid
from dataclasses import dataclass

import magic
import phonenumbers
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from lib_relaysms_payload_specs.generated import relaysms_spec_payload as rrs
from publisher import tokens
from publisher.config import DatabaseConfig, OfflinePublishConfig
from publisher.errors import PublisherError
from publisher.keys import pop_token_keys
from publisher.models import platform_adapter as platform_adapters
from publisher.models.payload_segment import create_if_not_exists as create_segment
from publisher.models.payload_segment import get_all_data
from publisher.models.payload_session import create as create_session
from publisher.models.payload_session import delete as delete_session
from publisher.models.payload_session import get_by_sender_and_session
from publisher.models.platform_adapter import PNBA, PlatformAdapter
from publisher.models.server_identity_key import get_private_key, mark_key_used
from publisher.models.token import Token, update_token_data
from publisher.models.token_hash import update_last_used as mark_token_hash_used
from publisher.platforms import ipc
from relaysms_adapter_sdk import AdapterError, Attachment, Message, SendRequest

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
    def __init__(
        self,
        message: str,
        *,
        platform_name: str | None = None,
        token: dict | None = None,
    ):
        super().__init__(message, platform_name=platform_name)
        # Refreshed before the send failed, so still the one to store.
        self.token = token


@dataclass(frozen=True)
class Delivery:
    """A decrypted payload ready to send; token_id is None for offline content."""

    adapter: PlatformAdapter
    request: SendRequest
    key_id: int
    token_id: int | None = None

    @property
    def platform(self) -> str:
        return self.adapter.name


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


def prepare(
    session: Session,
    payload_raw: bytes,
    sender_id: str,
    raw_segment: bytes,
    payload_type: rrs.V1PayloadsTypes,
    protocol: str | None = None,
    tag: str | None = None,
) -> Delivery | None:
    """Decrypt a payload, deleting its keys; None while segments are missing.

    The deletion only sticks if the session commits, so commit it after a
    successful send() and finish(), and roll it back otherwise.
    """
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
) -> Delivery:
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
) -> Delivery:
    token, _, ss_kid, es_kid, es_kid_pk, ec_kid_pk = pop_token_keys(
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
        rrs.v1_payload_support_protocols_from_u8(token.proto_id)
    except Exception:
        logger.exception("Unknown protocol %r on token %d.", token.proto_id, token_id)
        raise

    adapter = platform_adapters.get_for_protocol(
        session, token.platform, token.proto_id
    )
    request = SendRequest(message=_message(content), account=tokens.account(token))
    return Delivery(adapter, request, key_id=key_id, token_id=token.id)


def send(delivery: Delivery) -> dict | None:
    """Send through the adapter; return the token it refreshed, if any.

    Raises:
        AdapterIntegrationError: The adapter failed.
    """
    try:
        result = ipc.call(delivery.adapter, "send_message", delivery.request)
    except AdapterError as e:
        logger.error("Adapter %r failed: %s", delivery.platform, e.message)
        raise AdapterIntegrationError(
            f"Adapter error: {e.message}",
            platform_name=delivery.platform,
            token=e.token,
        ) from e
    logger.info("Published via %r.", delivery.platform)
    return result.get("token")


def store_token(session: Session, delivery: Delivery, new_token: dict | None) -> None:
    """Store a token the adapter refreshed, unless it was unlinked meanwhile."""
    token = session.get(Token, delivery.token_id) if delivery.token_id else None
    if token and new_token and new_token != token.token_data.get("token"):
        update_token_data(session, token, {**token.token_data, "token": new_token})
        logger.info("Stored the refreshed token for %r.", token.platform)


def finish(session: Session, delivery: Delivery, new_token: dict | None) -> None:
    """Record a successful send on its keys and token."""
    mark_key_used(session, delivery.key_id)
    store_token(session, delivery, new_token)
    token = session.get(Token, delivery.token_id) if delivery.token_id else None
    if token:
        mark_token_hash_used(session, token.token_hash)


def _publish_offline_content(
    session: Session,
    key_id: int,
    len_att: int,
    content_ciphertext: bytes,
) -> Delivery:
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
    return Delivery(adapter, SendRequest(message=_message(content)), key_id=key_id)


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


def _message(content: rrs.V1ContentsContainer) -> Message:
    attachments = ()
    data = content.get_attachment()
    if data:
        try:
            mimetype = magic.from_buffer(data[:2048], mime=True)
        except magic.MagicException:
            mimetype = None
        if not mimetype:
            logger.warning("Could not determine MIME type of attachment.")
            mimetype = "application/octet-stream"
        extension = mimetype.split("/")[-1] or "bin"
        filename = f"{uuid.uuid4().hex}.{extension}"
        attachments = (Attachment(data=data, filename=filename, mimetype=mimetype),)

    body = content.get_body().decode()
    match content.get_cat_id():
        case rrs.V1ContentCategories.TEXT:
            return Message(body=body, attachments=attachments)
        case rrs.V1ContentCategories.MESSAGE:
            return Message(
                body=body, recipient=_recipient(content), attachments=attachments
            )
        case rrs.V1ContentCategories.EMAIL:
            return Message(
                body=body,
                recipient=_recipient(content),
                subject=(content.get_subject() or b"").decode(),
                attachments=attachments,
            )
        case cat_id:
            logger.error("Content category not supported: %r", cat_id)
            raise PayloadNotSupportedError(f"Unsupported content category: {cat_id!r}")
