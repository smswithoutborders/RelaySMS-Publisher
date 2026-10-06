# SPDX-License-Identifier: GPL-3.0-only
"""Revoking stored platform tokens upstream and cleaning up idle ones."""

import datetime
import logging

from sqlalchemy.orm import Session

from lib_relaysms_payload_specs.generated import relaysms_spec_payload as rrs
from publisher.models import platform_adapter as platform_adapters
from publisher.models.platform_adapter import OAUTH2, PNBA
from publisher.models.token import Token, get_idle
from publisher.platforms import ipc

logger = logging.getLogger(__name__)


def revoke_oauth2_token_upstream(session: Session, token: Token) -> str | None:
    """Revoke an OAuth2 token at its platform; return the adapter's error, if any."""
    # Disabled adapters still revoke, so users can always unlink.
    adapter = platform_adapters.get_for_protocol(
        session, token.platform, OAUTH2, include_disabled=True
    )
    pipe = ipc.invoke(
        adapter_path=adapter.path,
        venv_path=adapter.venv_path,
        method="revoke_token",
        params={
            "token": token.token_data["token"],
            "base_path": adapter.assets_path,
        },
    )
    return pipe.get("error")


def revoke_pnba_token_upstream(session: Session, token: Token) -> str | None:
    """End a PNBA session at its platform; return the adapter's error, if any."""
    adapter = platform_adapters.get_for_protocol(
        session, token.platform, PNBA, include_disabled=True
    )
    pipe = ipc.invoke(
        adapter_path=adapter.path,
        venv_path=adapter.venv_path,
        method="invalidate_session",
        params={
            "phone_number": token.token_data["account_id"],
            "session": token.token_data["token"],
            "base_path": adapter.assets_path,
        },
    )
    return pipe.get("error")


def cleanup_idle_tokens(
    session: Session, older_than: datetime.datetime
) -> dict[str, int]:
    """Revoke and delete tokens unused since older_than; return counts by platform."""
    counts: dict[str, int] = {}
    for token in get_idle(session, older_than):
        _revoke_idle_token(session, token)
        counts[token.platform] = counts.get(token.platform, 0) + 1
        session.delete(token)
    session.flush()
    return counts


def _revoke_idle_token(session: Session, token: Token) -> None:
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
            error = revoke_oauth2_token_upstream(session, token)
        elif proto_id == rrs.V1PayloadsSupportedProtocols.PNBA:
            error = revoke_pnba_token_upstream(session, token)
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
