# SPDX-License-Identifier: GPL-3.0-only
"""Publication logic for RelaySMS payloads."""

import base64

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


def _get_adapter_params(
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
            logger.error("unsupported content category: %r", cat_id)
            raise ValueError(f"unsupported content category: {cat_id!r}")

    return params


def _consume_used_keys(token_hash: TokenHash, key_index: int, session: Session) -> None:
    session.execute(
        delete(ServerEphemeralKey).where(
            ServerEphemeralKey.token_hash_id == token_hash.id,
            ServerEphemeralKey.key_index == key_index,
        )
    )
    session.execute(
        delete(ClientEphemeralKey).where(
            ClientEphemeralKey.token_hash_id == token_hash.id,
            ClientEphemeralKey.key_index == key_index,
        )
    )
    mark_ss_kid_used(key_index, session)


def publish_platform_content(
    token_id: int,
    key_id: int,
    len_att: int,
    content_ciphertext: bytes,
    session: Session,
    adapter_manager: AdapterManager,
) -> None:
    """Decrypt and publish content to its target platform."""
    token, token_hash_obj, ss_kid, es_kid, es_kid_pk, ec_kid_pk = (
        get_keys_for_decryption(token_id=token_id, key_id=key_id, session=session)
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
        logger.exception("decryption failed for key_id=%d: %s", key_id, exc)
        raise ValueError("failed to decrypt content") from exc

    _consume_used_keys(token_hash=token_hash_obj, key_index=key_id, session=session)

    try:
        cat_id = rrs.v1_content_category_from_u8(token.cat_id)
    except Exception as exc:
        logger.exception("unknown cat_id=%r on token: %s", token.cat_id, exc)
        raise

    try:
        content = rrs.V1ContentsContainer.deserialize(content_bytes, cat_id, len_att)
    except Exception as exc:
        logger.exception("content deserialization failed: %s", exc)
        raise ValueError("failed to deserialize content") from exc

    try:
        proto_id = rrs.v1_payload_support_protocols_from_u8(token.proto_id)
    except Exception as exc:
        logger.exception("unknown proto_id=%r on token: %s", token.proto_id, exc)
        raise

    match proto_id:
        case rrs.V1PayloadsSupportedProtocols.O_AUTH20:
            adapter = adapter_manager.get_oauth2_adapter(token.platform)
            account_id = token.token_data["account_id"]
            params = _get_adapter_params(
                content=content,
                extras={
                    "sender_id": account_id,
                    "from_email": account_id,
                    "token": token.token_data["token"],
                },
            )
        case rrs.V1PayloadsSupportedProtocols.PNBA:
            adapter = adapter_manager.get_pnba_adapter(token.platform)
            params = _get_adapter_params(
                content=content,
                extras={
                    "phone_number": token.token_data["account_id"],
                    "base_path": adapter.assets_path,
                },
            )
        case _:
            logger.error("unsupported protocol: %r", proto_id)
            raise ValueError(f"unsupported protocol: {proto_id!r}")

    pipe = AdapterIPCHandler.invoke(
        adapter_path=adapter.path,
        venv_path=adapter.venv_path,
        method="send_message",
        params=params,
    )

    if pipe.get("error"):
        logger.error("failed to publish platform content: %s", pipe["error"])
        raise ValueError("failed to publish platform content")

    mark_token_hash_used(token_hash_obj, session)
    result = pipe.get("result", {})

    if proto_id == rrs.V1PayloadsSupportedProtocols.O_AUTH20:
        refreshed_token = result.get("refreshed_token") or {}
        new_refresh_token = refreshed_token.get("refresh_token")
        old_refresh_token = token.token_data["token"].get("refresh_token")
        if new_refresh_token and new_refresh_token != old_refresh_token:
            update_token_data(
                token, {**token.token_data, "token": refreshed_token}, session
            )
            logger.info("successfully refreshed token for platform %r", token.platform)


def publish_bridge_content(
    key_id: int,
    len_att: int,
    content_ciphertext: bytes,
    session: Session,
    adapter_manager: AdapterManager,
) -> None:
    """Decrypt and publish content to its target bridge."""
    ss_kid = get_private_key(key_id, session).private_bytes_raw()

    try:
        offline_response = rrs.v1_bridge_offline_first_publisher_decrypt(
            ss=ss_kid,
            ec_pk=None,
            sc_pk_enc=None,
            rx_payload=content_ciphertext,
        )
    except Exception as exc:
        logger.exception("decryption failed for key_id=%d: %s", key_id, exc)
        raise ValueError("failed to decrypt content") from exc

    mark_ss_kid_used(key_id, session)

    cat_id = rrs.V1ContentCategories.BRIDGE
    try:
        content = rrs.V1ContentsContainer.deserialize(
            offline_response.get_payload(), cat_id, len_att
        )
    except Exception as exc:
        logger.exception("content deserialization failed: %s", exc)
        raise ValueError("failed to deserialize content") from exc

    adapter = adapter_manager.get_pnba_adapter("rmail")
    params = _get_adapter_params(content=content)

    pipe = AdapterIPCHandler.invoke(
        adapter_path=adapter.path,
        venv_path=adapter.venv_path,
        method="send_message",
        params=params,
    )

    if pipe.get("error"):
        logger.error("failed to publish bridge content: %s", pipe["error"])
        raise ValueError("failed to publish bridge content")


def store_segment_and_try_join(
    *, sender_id: str, payload_raw: bytes, raw_segment: bytes, db: Session
) -> rrs.V1Payloads | None:
    """Store an incoming segment and attempt assembly.

    Returns the joined payload if complete, None if still waiting.
    Cleans up the session on successful join.
    """
    sess_id = rrs.v1_get_payload_session_id(payload_raw)

    payload_session = get_by_sender_and_session(
        sender_id=sender_id, session_id=sess_id, session=db
    )
    if payload_session is None:
        payload_session = create_session(
            sender_id=sender_id, session_id=sess_id, session=db
        )

    create_segment(session_id=payload_session.id, data=raw_segment, session=db)

    segment_data = get_all_data(session_id=payload_session.id, session=db)

    try:
        joined = rrs.V1Payloads.join(segment_data)
    except Exception:
        return None

    delete_session(payload_session, db)
    return joined
