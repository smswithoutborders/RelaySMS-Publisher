# SPDX-License-Identifier: GPL-3.0-only
"""v1 Services for the REST API."""

from sqlalchemy.orm import Session

from grpc_services.v3.utils import (
    get_keys_for_decryption,
    get_oauth2_adapter,
    get_pnba_adapter,
)
from lib_relaysms_payload_specs.generated import relaysms_spec_payload as rrs
from logutils import get_logger
from models.payload_segment import create_if_not_exists as create_segment
from models.payload_segment import get_all_data
from models.payload_session import create as create_session
from models.payload_session import delete as delete_session
from models.payload_session import get_by_sender_and_session
from models.server_identity_key import mark_key_used as mark_ss_kid_used
from models.token import update_token_data
from models.token_hash import TokenHash
from platforms.adapter_ipc_handler import AdapterIPCHandler
from platforms.adapter_manager import AdapterManager

logger = get_logger(__name__)


def _get_adapter_params(
    token_data: dict, content: rrs.V1ContentsContainer, *, extras: dict | None = None
) -> dict:
    cat_id = content.get_cat_id()
    print(">>>>>>>>> ATTACHMENT:", content.get_attachment())
    extra_params = extras or {}

    match cat_id:
        case rrs.V1ContentCategories.EMAIL:
            return {
                "from_email": token_data["account_id"],
                "to_email": content.get_to().decode(),
                "subject": content.get_subject().decode(),
                "message": content.get_body().decode(),
                **extra_params,
            }
        case rrs.V1ContentCategories.MESSAGE:
            return {
                "recipient": content.get_to().decode(),
                "message": content.get_body().decode(),
                **extra_params,
            }
        case rrs.V1ContentCategories.TEXT:
            return {"message": content.get_body().decode(), **extra_params}
        case _:
            logger.error("unsupported content category: %r", cat_id)
            raise ValueError(f"unsupported content category: {cat_id!r}")


def _consume_used_keys(token_hash: TokenHash, key_index: int, session: Session) -> None:
    session.delete(token_hash.server_keys[0])
    session.delete(token_hash.client_keys[0])
    mark_ss_kid_used(key_index, session)


def publish_content(
    token_id: bytes,
    key_id: int,
    len_att: int,
    content_ciphertext: bytes,
    session: Session,
    adapter_manager: AdapterManager,
) -> None:
    """Decrypt and publish content to its target platform."""
    token, token_hash_obj, ss_kid, es_kid, es_kid_pk, ec_kid_pk = (
        get_keys_for_decryption(token_id_bytes=token_id, key_id=key_id, session=session)
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

    if token.protocol == "oauth2":
        adapter = get_oauth2_adapter(adapter_manager, token.platform)
        params = _get_adapter_params(
            token_data=token.token_data,
            content=content,
            extras={
                "sender_id": token.token_data["account_id"],
                "token": token.token_data["token"],
            },
        )
    elif token.protocol == "pnba":
        adapter = get_pnba_adapter(adapter_manager, token.platform)
        params = _get_adapter_params(
            token_data=token.token_data,
            content=content,
            extras={
                "phone_number": token.token_data["token"],
                "base_path": adapter.assets_path,
            },
        )
    else:
        logger.error("unsupported protocol: %r", token.protocol)
        raise ValueError(f"unsupported protocol: {token.protocol!r}")

    pipe = AdapterIPCHandler.invoke(
        adapter_path=adapter.path,
        venv_path=adapter.venv_path,
        method="send_message",
        params=params,
    )

    if pipe.get("error"):
        logger.error("failed to publish content: %s", pipe["error"])
        raise ValueError("failed to publish content")

    result = pipe.get("result", {})

    if token.protocol == "oauth2":
        refreshed_token = result.get("refreshed_token") or {}
        new_refresh_token = refreshed_token.get("refresh_token")
        old_refresh_token = token.token_data["token"].get("refresh_token")
        if new_refresh_token and new_refresh_token != old_refresh_token:
            update_token_data(
                token, {**token.token_data, "token": refreshed_token}, session
            )
            logger.info("refreshed OAuth2 token for platform %r", token.platform)


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
