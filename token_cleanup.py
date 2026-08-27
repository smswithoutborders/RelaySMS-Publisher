# SPDX-License-Identifier: GPL-3.0-only
"""Idle token cleanup."""

import datetime

from sqlalchemy.orm import Session

from lib_relaysms_payload_specs.generated import relaysms_spec_payload as rrs
from logutils import get_logger
from models.token import Token, get_idle
from platforms.adapter_manager import AdapterManager
from token_revocation import revoke_oauth2_token_upstream, revoke_pnba_token_upstream

logger = get_logger(__name__)


def _revoke_upstream(token: Token, adapter_manager: AdapterManager) -> None:
    try:
        proto_id = rrs.v1_payload_support_protocols_from_u8(token.proto_id)
    except Exception:
        logger.warning(
            "Unknown protocol %r on idle token %d; skipping upstream revoke.",
            token.proto_id,
            token.token_id,
        )
        return

    try:
        if proto_id == rrs.V1PayloadsSupportedProtocols.O_AUTH20:
            error = revoke_oauth2_token_upstream(token, adapter_manager)
        elif proto_id == rrs.V1PayloadsSupportedProtocols.PNBA:
            error = revoke_pnba_token_upstream(token, adapter_manager)
        else:
            return

        if error:
            logger.error(
                "Upstream revoke failed for idle token %d (%r): %s",
                token.token_id,
                token.platform,
                error,
            )
    except NotImplementedError:
        logger.warning(
            "No adapter for platform %r; skipping upstream revoke for token %d.",
            token.platform,
            token.token_id,
        )
    except Exception:
        logger.exception(
            "Unexpected error revoking idle token %d upstream.", token.token_id
        )


def cleanup_idle_tokens(
    older_than: datetime.datetime, session: Session, adapter_manager: AdapterManager
) -> dict[str, int]:
    counts: dict[str, int] = {}
    for token in get_idle(older_than, session):
        _revoke_upstream(token, adapter_manager)
        counts[token.platform] = counts.get(token.platform, 0) + 1
        session.delete(token)
    session.flush()
    return counts
