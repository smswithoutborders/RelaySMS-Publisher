# SPDX-License-Identifier: GPL-3.0-only
"""Revoking stored platform tokens upstream and deleting idle ones."""

import datetime
import logging

from sqlalchemy.orm import Session

from publisher.models import platform_adapter as platform_adapters
from publisher.models.platform_adapter import PlatformAdapter
from publisher.models.token import Token, get_idle
from publisher.platforms import ipc
from relaysms_adapter_sdk import Account, AdapterError, RevokeRequest

logger = logging.getLogger(__name__)


def account(token: Token) -> Account:
    """The linked account a stored token belongs to, as adapters take it."""
    return Account(
        identifier=token.token_data["account_id"], token=token.token_data["token"]
    )


type Revocation = tuple[PlatformAdapter, RevokeRequest]


def revocation(session: Session, token: Token) -> Revocation | None:
    """Read what revoking a token takes, before the token is deleted.

    None when no adapter serves its platform. Run it with revoke_upstream once the
    deletion commits.
    """
    try:
        # Disabled adapters still revoke, so users can always unlink.
        adapter = platform_adapters.get_for_protocol(
            session, token.platform, token.proto_id, include_disabled=True
        )
    except NotImplementedError:
        logger.warning(
            "No adapter for %r; token %d can't be revoked upstream.",
            token.platform,
            token.token_id,
        )
        return None
    return adapter, RevokeRequest(account(token))


def revoke_upstream(revocation: Revocation | None) -> None:
    """Revoke at the platform, outside any transaction; failures are only logged."""
    if revocation is None:
        return
    adapter, request = revocation
    try:
        ipc.call(adapter, "revoke", request)
    except AdapterError as e:
        logger.error("Upstream revoke failed at %r: %s", adapter.name, e.message)
    except Exception:
        logger.exception("Unexpected error revoking a token at %r.", adapter.name)


def delete_idle(
    session: Session, older_than: datetime.datetime
) -> list[tuple[str, Revocation | None]]:
    """Delete tokens unused since older_than; return their platforms and revocations."""
    deleted = []
    for token in get_idle(session, older_than):
        deleted.append((token.platform, revocation(session, token)))
        session.delete(token)
    session.flush()
    return deleted
