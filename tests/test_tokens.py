# SPDX-License-Identifier: GPL-3.0-only

import datetime

import pytest

from publisher import db, tokens
from publisher.models.platform_adapter import OAUTH2, PlatformAdapter
from publisher.models.token import Token
from publisher.platforms import ipc, manager
from tests.helpers import add_adapter, link_account

LATER = datetime.datetime.now(datetime.UTC) + datetime.timedelta(days=1)


class Calls(list):
    response: dict


@pytest.fixture
def calls(monkeypatch):
    """Answers every adapter call with `response` and records the method."""
    calls = Calls()
    calls.response = {"result": True}

    def invoke(adapter_path, venv_path, method, params=None):
        calls.append(method)
        return calls.response

    monkeypatch.setattr(ipc, "invoke", invoke)
    return calls


@pytest.fixture(autouse=True)
def disabled_gmail(test_db, platforms_config):
    add_adapter("gmail", OAUTH2)
    with db.get_session() as session:
        manager.set_enabled(session, session.get(PlatformAdapter, "gmail-0"), False)


def _cleanup():
    with db.get_session() as session:
        return tokens.cleanup_idle_tokens(session, LATER)


def _tokens():
    with db.get_session() as session:
        return session.query(Token).count()


def test_idle_tokens_are_revoked_through_a_disabled_adapter(calls):
    link_account("gmail", OAUTH2)

    assert _cleanup() == {"gmail": 1}
    assert calls == ["revoke_token"]
    assert _tokens() == 0


def test_a_failed_upstream_revoke_still_deletes_the_token(calls, caplog):
    calls.response = {"error": "token expired"}
    link_account("gmail", OAUTH2)

    _cleanup()

    assert _tokens() == 0
    assert "Upstream revoke failed" in caplog.text
