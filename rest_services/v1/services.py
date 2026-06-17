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
from models.client_ephemeral_key import (
    delete_by_index as delete_client_key_by_index,
)
from models.server_ephemeral_key import (
    delete_by_index as delete_server_key_by_index,
)
from models.server_identity_key import mark_key_used as mark_ss_kid_used
from platforms.adapter_ipc_handler import AdapterIPCHandler

logger = get_logger(__name__)


def _get_adapter_params(
    token_data: dict, content: rrs.V1ContentsContainer, *, extras: dict | None = None
) -> dict:
    """Build the params dict expected by the platform adapter's send_message method."""
    cat_id = content.get_cat_id()
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
            raise ValueError(f"unsupported content category: {cat_id!r}")


def _consume_used_keys(token_hash_id: int, key_index: int, session: Session) -> None:
    """Delete the used ephemeral key pair and record ss_kid usage."""
    delete_client_key_by_index(
        token_hash_id=token_hash_id, key_index=key_index, session=session
    )
    delete_server_key_by_index(
        token_hash_id=token_hash_id, key_index=key_index, session=session
    )
    mark_ss_kid_used(key_index, session)


def publish_content(
    token_id: bytes,
    key_id: int,
    len_att: int,
    content_ciphertext: bytes,
    session: Session,
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
        logger.error("decryption failed for key_id=%d: %s", key_id, exc)
        raise ValueError("failed to decrypt content") from exc

    _consume_used_keys(
        token_hash_id=token_hash_obj.id, key_index=key_id, session=session
    )

    try:
        cat_id = rrs.v1_content_category_from_u8(token.cat_id)
    except Exception as exc:
        logger.error("unknown cat_id=%r on token: %s", token.cat_id, exc)
        raise

    try:
        content = rrs.V1ContentsContainer.deserialize(content_bytes, cat_id, len_att)
    except Exception as exc:
        logger.error("content deserialization failed: %s", exc)
        raise ValueError("failed to deserialize content") from exc

    if token.protocol == "oauth2":
        adapter = get_oauth2_adapter(token.platform)
        params = _get_adapter_params(
            token.token_data,
            content,
            extras={
                "sender_id": token.token_data["account_id"],
                "token": token.token_data["token"],
            },
        )
    elif token.protocol == "pnba":
        adapter = get_pnba_adapter(token.platform)
        params = _get_adapter_params(
            token.token_data,
            content,
            extras={
                "phone_number": token.token_data["token"],
                "base_path": adapter["assets_path"],
            },
        )
    else:
        raise ValueError(f"unsupported protocol: {token.protocol!r}")

    pipe = AdapterIPCHandler.invoke(
        adapter_path=adapter["path"],
        venv_path=adapter["venv_path"],
        method="send_message",
        params=params,
    )

    if pipe.get("error"):
        logger.error("failed to publish content: %s", pipe["error"])
        raise ValueError("failed to publish content")
