# SPDX-License-Identifier: GPL-3.0-only
"""Publication processing pipeline service."""

import base64
import magic
import uuid
from typing import Optional

from sqlalchemy.orm import Session

from keys import KeyManager
from lib_relaysms_payload_specs.generated import relaysms_spec_payload as rrs
from logutils import get_logger
from models.payload_segment import create_if_not_exists as create_segment
from models.payload_segment import get_all_data
from models.payload_session import create as create_session
from models.payload_session import delete as delete_session
from models.payload_session import get_by_sender_and_session
from models.server_identity_key import get_private_key
from models.token import update_token_data
from models.token_hash import update_last_used as mark_token_hash_used
from platforms.adapter_ipc_handler import AdapterIPCHandler
from platforms.adapter_manager import AdapterManager

logger = get_logger(__name__)


class PublicationError(Exception):
    pass


class PayloadMalformedError(PublicationError):
    pass


class PayloadNotSupportedError(PublicationError):
    pass


class AdapterIntegrationError(PublicationError):
    pass


class PublicationService:
    """Assembles, decrypts, and routes payloads to platform adapters."""

    def __init__(self, session: Session, adapter_manager: AdapterManager):
        self.session = session
        self.adapter_manager = adapter_manager
        self.key_manager = KeyManager(session=session)

    @staticmethod
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
        self,
        payload_raw: bytes,
        sender_address: str,
        raw_segment: bytes,
        payload_type: rrs.V1PayloadsTypes,
    ) -> bool:
        """Processes incoming payload and publishes to target platform."""
        payload = self._assemble(
            payload_raw=payload_raw,
            sender_address=sender_address,
            raw_segment=raw_segment,
            payload_type=payload_type,
        )

        if payload is None:
            return False

        self._dispatch(payload)
        return True

    def _assemble(
        self,
        payload_raw: bytes,
        sender_address: str,
        raw_segment: bytes,
        payload_type: rrs.V1PayloadsTypes,
    ) -> Optional[rrs.V1Payloads]:
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
                return self._store_segment_and_try_join(
                    sender_id=sender_address,
                    payload_raw=payload_raw,
                    raw_segment=raw_segment,
                )

            case _:
                logger.error("Payload type not supported: %r", payload_type)
                raise PayloadNotSupportedError(f"Unsupported type: {payload_type!r}")

    def _dispatch(self, payload: rrs.V1Payloads) -> None:
        token_id = payload.get_t_id()

        if token_id is None:
            self._publish_offline_content(
                key_id=payload.get_kid(),
                len_att=payload.get_len_att(),
                content_ciphertext=payload.get_content(),
            )
            return

        self._publish_online_content(
            token_id=token_id,
            key_id=payload.get_kid(),
            len_att=payload.get_len_att(),
            content_ciphertext=payload.get_content(),
        )

    def _publish_online_content(
        self,
        token_id: int,
        key_id: int,
        len_att: int,
        content_ciphertext: bytes,
    ) -> None:
        token, token_hash_obj, ss_kid, es_kid, es_kid_pk, ec_kid_pk = (
            self.key_manager.get_token_and_keys_for_decryption(
                token_id=token_id, key_id=key_id
            )
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
            raise PayloadMalformedError("Decryption failed.") from exc

        self.key_manager.mark_identity_key_used(key_id)

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
        except Exception:
            logger.exception("Failed to deserialize content for token %d.", token_id)
            raise PayloadMalformedError("Content deserialization failed.")

        try:
            proto_id = rrs.v1_payload_support_protocols_from_u8(token.proto_id)
        except Exception:
            logger.exception(
                "Unknown protocol %r on token %d.", token.proto_id, token_id
            )
            raise

        account_id = token.token_data["account_id"]
        match proto_id:
            case rrs.V1PayloadsSupportedProtocols.O_AUTH20:
                adapter = self.adapter_manager.get_oauth2_adapter(token.platform)
                params = self._get_adapter_params(
                    content=content,
                    extras={
                        "sender_id": account_id,
                        "from_email": account_id,
                        "token": token.token_data["token"],
                    },
                )
            case rrs.V1PayloadsSupportedProtocols.PNBA:
                adapter = self.adapter_manager.get_pnba_adapter(token.platform)
                params = self._get_adapter_params(
                    content=content,
                    extras={
                        "phone_number": account_id,
                        "base_path": adapter.assets_path,
                    },
                )
            case _:
                logger.error(
                    "Protocol %r not supported on token %d.", proto_id, token_id
                )
                raise PayloadNotSupportedError(f"Unsupported protocol: {proto_id!r}")

        pipe = AdapterIPCHandler.invoke(
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
            raise AdapterIntegrationError("Failed to send message via adapter.")

        mark_token_hash_used(token_hash_obj, self.session)
        logger.info("Published message for token %d via %r.", token_id, token.platform)

        if proto_id == rrs.V1PayloadsSupportedProtocols.O_AUTH20:
            self._maybe_refresh_token(token, pipe.get("result", {}))

    def _maybe_refresh_token(self, token, result: dict) -> None:
        refreshed_token = result.get("refreshed_token") or {}
        new_refresh_token = refreshed_token.get("refresh_token")
        old_refresh_token = token.token_data["token"].get("refresh_token")
        if new_refresh_token and new_refresh_token != old_refresh_token:
            update_token_data(
                token, {**token.token_data, "token": refreshed_token}, self.session
            )
            logger.info("Refreshed OAuth token data for %r.", token.platform)

    def _publish_offline_content(
        self, key_id: int, len_att: int, content_ciphertext: bytes
    ) -> None:
        ss_kid = get_private_key(key_id, self.session).private_bytes_raw()

        try:
            offline_first = rrs.OfflineFirst.deserialize(content_ciphertext)
            content_obj = rrs.OfflineFirst.decrypt(
                ss=ss_kid, offline_first=offline_first
            )
        except Exception:
            logger.exception("Failed to decrypt offline payload with key %d.", key_id)
            raise PayloadMalformedError("Decryption failed.")

        self.key_manager.mark_identity_key_used(key_id)

        try:
            cat_id = rrs.V1ContentCategories.BRIDGE
            content = rrs.V1ContentsContainer.deserialize(
                data=content_obj.get_payload(), cat_id=cat_id, len_att=len_att
            )
        except Exception:
            logger.exception("Failed to deserialize offline content")
            raise PayloadMalformedError("Content deserialization failed.")

        adapter = self.adapter_manager.get_pnba_adapter("rmail")
        params = self._get_adapter_params(content=content)

        pipe = AdapterIPCHandler.invoke(
            adapter_path=adapter.path,
            venv_path=adapter.venv_path,
            method="send_message",
            params=params,
        )

        if pipe.get("error"):
            logger.error("Adapter %r failed: %s", adapter.name, pipe["error"])
            raise AdapterIntegrationError("Failed to send message via adapter.")

        logger.info("Published offline content via %r.", adapter.name)

    def _store_segment_and_try_join(
        self, *, sender_id: str, payload_raw: bytes, raw_segment: bytes
    ) -> Optional[rrs.V1Payloads]:
        sess_id = rrs.v1_get_payload_session_id(payload_raw)

        payload_session = get_by_sender_and_session(
            sender_id=sender_id, session_id=sess_id, session=self.session
        )
        if payload_session is None:
            payload_session = create_session(
                sender_id=sender_id, session_id=sess_id, session=self.session
            )

        create_segment(
            session_id=payload_session.id, data=raw_segment, session=self.session
        )
        segment_data = get_all_data(session_id=payload_session.id, session=self.session)

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

        delete_session(payload_session, self.session)
        logger.info(
            "Session %s assembled from %d segments.", sess_id, len(segment_data)
        )
        return joined

    def _get_adapter_params(
        self, content: rrs.V1ContentsContainer, *, extras: dict | None = None
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
                params["recipient"] = content.get_to().decode()
                params["message"] = message

            case rrs.V1ContentCategories.EMAIL | rrs.V1ContentCategories.BRIDGE:
                params["to_email"] = content.get_to().decode()
                params["subject"] = content.get_subject().decode()
                params["message"] = message

            case _:
                logger.error("Content category not supported: %r", cat_id)
                raise PayloadNotSupportedError(
                    f"Unsupported content category: {cat_id!r}"
                )

        return params
