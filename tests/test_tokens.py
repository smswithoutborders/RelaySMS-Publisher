# SPDX-License-Identifier: GPL-3.0-only

import datetime

import pytest

from publisher import db, tokens
from publisher.models.platform_adapter import OAUTH2, PlatformAdapter
from publisher.models.token import Token
from publisher.platforms import manager
from relaysms_adapter_sdk import Account, UpstreamError
from tests.helpers import add_adapter, link_account

LATER = datetime.datetime.now(datetime.UTC) + datetime.timedelta(days=1)


@pytest.fixture
def calls(adapter_calls):
    return adapter_calls


@pytest.fixture(autouse=True)
def disabled_gmail(test_db, platforms_config):
    add_adapter("gmail", OAUTH2)
    with db.get_session() as session:
        manager.set_enabled(session, session.get(PlatformAdapter, "gmail-0"), False)


def _cleanup():
    with db.get_session() as session:
        deleted = tokens.delete_idle(session, LATER)
    for _, revocation in deleted:
        tokens.revoke_upstream(revocation)
    return [platform for platform, _ in deleted]


def _tokens():
    with db.get_session() as session:
        return session.query(Token).count()


def test_idle_tokens_are_revoked_through_a_disabled_adapter(calls):
    link_account("gmail", OAUTH2)

    assert _cleanup() == ["gmail"]
    [(_, method, request)] = calls.calls
    assert method == "revoke"
    assert request.account == Account("user@example.org", token={"t": "1"})
    assert _tokens() == 0


def test_a_failed_upstream_revoke_still_deletes_the_token(calls, caplog):
    calls.results["revoke"] = UpstreamError("token expired")
    link_account("gmail", OAUTH2)

    _cleanup()

    assert _tokens() == 0
    assert "Upstream revoke failed" in caplog.text
