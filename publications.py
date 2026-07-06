# SPDX-License-Identifier: GPL-3.0-only

import base64
from typing import Optional

from sqlalchemy import delete
from sqlalchemy.orm import Session

from keys import get_keys_for_decryption
from lib_relaysms_payload_specs.generated import relaysms_spec_payload as rrs
from logutils import get_logger
from models.client_ephemeral_key import ClientEphemeralKey
from models.payload_segment import create_if_not_exists as create_segment
from models.payload_segment import get_all_data
from models.payload_session import create as create_session
from models.payload_session import delete as delete_session
from models.payload_session import get_by_sender_and_session
from models.server_ephemeral_key import ServerEphemeralKey
from models.server_identity_key import get_private_key
from models.server_identity_key import mark_key_used as mark_ss_kid_used
from models.token import update_token_data
from models.token_hash import TokenHash
from models.token_hash import update_last_used as mark_token_hash_used
from platforms.adapter_ipc_handler import AdapterIPCHandler
from platforms.adapter_manager import AdapterManager

logger = get_logger(__name__)


class PublicationError(Exception):
    """Base error for all publication pipeline failures."""


class PayloadMalformedError(PublicationError):
    """Raised when incoming data is unreadable or corrupt."""


class PayloadNotSupportedError(PublicationError):
    """Raised when an unhandled protocol or category is sent."""


class AdapterIntegrationError(PublicationError):
    """Raised when a downstream platform adapter fails to deliver."""


class PublicationService:
    """Handles rebuilding, decrypting, and sending payloads to platforms."""

    def __init__(self, session: Session, adapter_manager: AdapterManager):
        self.session = session
        self.adapter_manager = adapter_manager

    @staticmethod
    def validate(text_payload: str) -> tuple[bytes, bytes, rrs.V1PayloadsTypes]:
        """Validates, decodes, and types the raw text payload input."""
        try:
            payload_bytes = base64.b64decode(text_payload)
        except Exception as exc:
            raise PayloadMalformedError("Payload is not valid Base64.") from exc

        try:
            payload_type = rrs.v1_get_payload_type(payload_bytes)
        except Exception as exc:
            logger.exception("Failed to read payload type")
            raise PayloadMalformedError("Payload structure is invalid.") from exc

        return payload_bytes, text_payload.encode(), payload_type

    def publish(
        self,
        payload_raw: bytes,
        sender_address: str,
        raw_segment: bytes,
        payload_type: rrs.V1PayloadsTypes,
    ) -> Optional[str]:
        """Main entrypoint to process and send an incoming message payload."""
        payload = self._assemble(
            payload_raw=payload_raw,
            sender_address=sender_address,
            raw_segment=raw_segment,
            payload_type=payload_type,
        )

        if payload is None:
            logger.info("Segment stored, awaiting remaining parts")
            return None

        self._dispatch(payload)
        return "Content published successfully"

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
                    logger.exception("Failed to deserialize standalone payload")
                    raise PayloadMalformedError(
                        "Failed to read message payload."
                    ) from exc

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
                logger.error("Unsupported payload type %r", payload_type)
                raise PayloadNotSupportedError(
                    f"Payload type '{payload_type!r}' is not supported."
                )

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
            get_keys_for_decryption(
                token_id=token_id, key_id=key_id, session=self.session
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
            logger.exception("Decryption failed for token %s, key %s", token_id, key_id)
            raise PayloadMalformedError("Unable to decrypt message content.") from exc

        self._consume_used_keys(token_hash=token_hash_obj, key_index=key_id)

        try:
            cat_id = rrs.v1_content_category_from_u8(token.cat_id)
        except Exception:
            logger.exception(
                "Unknown content category %r for token %s", token.cat_id, token_id
            )
            raise

        try:
            content = rrs.V1ContentsContainer.deserialize(
                content_bytes, cat_id, len_att
            )
        except Exception as exc:
            logger.exception(
                "Failed to deserialize content container for token %s", token_id
            )
            raise PayloadMalformedError(
                "Decrypted container format is invalid."
            ) from exc

        try:
            proto_id = rrs.v1_payload_support_protocols_from_u8(token.proto_id)
        except Exception:
            logger.exception(
                "Unknown protocol %r for token %s", token.proto_id, token_id
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
                logger.error("Unsupported protocol %r for token %s", proto_id, token_id)
                raise PayloadNotSupportedError(
                    f"Protocol '{proto_id!r}' is not supported."
                )

        pipe = AdapterIPCHandler.invoke(
            adapter_path=adapter.path,
            venv_path=adapter.venv_path,
            method="send_message",
            params=params,
        )

        if pipe.get("error"):
            logger.error(
                "Adapter %r failed for token %s: %s",
                token.platform,
                token_id,
                pipe["error"],
            )
            raise AdapterIntegrationError(f"Platform adapter failed: {pipe['error']}")

        mark_token_hash_used(token_hash_obj, self.session)
        logger.info("Published token %s via %r", token_id, token.platform)

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
            logger.info("Refreshed OAuth token for platform %r", token.platform)

    def _publish_offline_content(
        self,
        key_id: int,
        len_att: int,
        content_ciphertext: bytes,
    ) -> None:
        ss_kid = get_private_key(key_id, self.session).private_bytes_raw()

        try:
            offline_response = rrs.v1_bridge_offline_first_publisher_decrypt(
                ss=ss_kid,
                ec_pk=None,
                sc_pk_enc=None,
                rx_payload=content_ciphertext,
            )
        except Exception as exc:
            logger.exception("Offline decryption failed for key %s", key_id)
            raise PayloadMalformedError("Unable to decrypt offline content.") from exc

        mark_ss_kid_used(key_id, self.session)

        cat_id = rrs.V1ContentCategories.BRIDGE
        try:
            content = rrs.V1ContentsContainer.deserialize(
                offline_response.get_payload(), cat_id, len_att
            )
        except Exception as exc:
            logger.exception(
                "Offline content deserialization failed for key %s", key_id
            )
            raise PayloadMalformedError(
                "Decrypted offline container format is invalid."
            ) from exc

        adapter = self.adapter_manager.get_pnba_adapter("rmail")
        params = self._get_adapter_params(content=content)

        pipe = AdapterIPCHandler.invoke(
            adapter_path=adapter.path,
            venv_path=adapter.venv_path,
            method="send_message",
            params=params,
        )

        if pipe.get("error"):
            logger.error("Offline adapter failed for key %s: %s", key_id, pipe["error"])
            raise AdapterIntegrationError(f"Offline adapter failed: {pipe['error']}")

        logger.info("Published offline content for key %s", key_id)

    def _store_segment_and_try_join(
        self,
        *,
        sender_id: str,
        payload_raw: bytes,
        raw_segment: bytes,
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
        except Exception:
            logger.debug(
                "Session %s incomplete: %d segment(s) stored",
                sess_id,
                len(segment_data),
            )
            return None

        delete_session(payload_session, self.session)
        logger.info(
            "Session %s fully assembled from %d segment(s)", sess_id, len(segment_data)
        )
        return joined

    def _get_adapter_params(
        self,
        content: rrs.V1ContentsContainer,
        *,
        extras: dict | None = None,
    ) -> dict:
        cat_id = content.get_cat_id()
        params = dict(extras) if extras else {}

        attachment = content.get_attachment()
        if attachment:
            params["attachments"] = [{"data": base64.b64encode(attachment).decode()}]

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
                logger.error("Unsupported content category %r", cat_id)
                raise PayloadNotSupportedError(
                    f"Content category '{cat_id!r}' is not supported."
                )

        return params

    def _consume_used_keys(self, token_hash: TokenHash, key_index: int) -> None:
        self.session.execute(
            delete(ServerEphemeralKey).where(
                ServerEphemeralKey.token_hash_id == token_hash.id,
                ServerEphemeralKey.key_index == key_index,
            )
        )
        self.session.execute(
            delete(ClientEphemeralKey).where(
                ClientEphemeralKey.token_hash_id == token_hash.id,
                ClientEphemeralKey.key_index == key_index,
            )
        )
        mark_ss_kid_used(key_index, self.session)
        logger.debug("Consumed ephemeral keys for key_index %s", key_index)
