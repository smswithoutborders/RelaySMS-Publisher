# SPDX-License-Identifier: GPL-3.0-only

import datetime
from unittest.mock import MagicMock

import pytest
from sqlalchemy import select

import db as db_module
import models  # noqa: F401  registers all model classes on Base.metadata
import tasks.cleanup_task as cleanup_task
from models.client_ephemeral_key import ClientEphemeralKey
from models.server_ephemeral_key import ServerEphemeralKey
from models.token import Token
from models.token import create as create_token
from models.token_hash import create as create_token_hash

DAY = datetime.timedelta(days=1)
OAUTH2 = 0
PNBA = 1


@pytest.fixture(autouse=True)
def _in_memory_db(monkeypatch):
    monkeypatch.setenv("MODE", "testing")
    db_module.dispose_engine()
    db_module.Base.metadata.create_all(db_module.get_engine())
    yield
    db_module.dispose_engine()


@pytest.fixture(autouse=True)
def _adapter_manager(monkeypatch):
    manager = MagicMock()
    manager.get_oauth2_adapter.side_effect = NotImplementedError("no adapter")
    manager.get_pnba_adapter.side_effect = NotImplementedError("no adapter")
    monkeypatch.setattr(cleanup_task, "_get_adapter_manager", lambda: manager)
    return manager


def _make_token(
    session, *, platform, proto_id, created_days_ago, last_used_days_ago=None
):
    token = create_token(
        platform=platform,
        cat_id=1,
        proto_id=proto_id,
        token_data={"account_id": "user@example.com", "token": {}},
        session=session,
    )
    token_hash, _ = create_token_hash(token.id, session)

    now = datetime.datetime.now(datetime.timezone.utc)
    token.created_at = now - created_days_ago * DAY
    if last_used_days_ago is not None:
        token_hash.last_used_at = now - last_used_days_ago * DAY
    session.add_all([token, token_hash])
    session.flush()
    return token, token_hash


def _remaining_token_ids() -> set[int]:
    with db_module.get_session() as session:
        return set(session.scalars(select(Token.id)).all())


def test_cleanup_idle_tokens_deletes_only_idle_ones(_adapter_manager, caplog):
    caplog.set_level("INFO")
    with db_module.get_session() as session:
        fresh_token, _ = _make_token(
            session, platform="gmail", proto_id=OAUTH2, created_days_ago=0
        )
        idle_token, _ = _make_token(
            session, platform="gmail", proto_id=OAUTH2, created_days_ago=100
        )
        active_token, _ = _make_token(
            session,
            platform="gmail",
            proto_id=OAUTH2,
            created_days_ago=100,
            last_used_days_ago=1,
        )
        fresh_id, idle_id, active_id = fresh_token.id, idle_token.id, active_token.id

    cleanup_task.cleanup_idle_tokens()

    assert _remaining_token_ids() == {fresh_id, active_id}
    assert "Cleaned up 1 idle token(s): {'gmail': 1}" in caplog.text
    _adapter_manager.get_oauth2_adapter.assert_called_once_with("gmail")


def test_cleanup_idle_tokens_cascades_ephemeral_key_deletes(_adapter_manager):
    with db_module.get_session() as session:
        _, idle_hash = _make_token(
            session, platform="gmail", proto_id=OAUTH2, created_days_ago=100
        )
        session.add(
            ServerEphemeralKey(
                token_hash_id=idle_hash.id,
                key_index=0,
                private_key=b"k" * 32,
                public_key=b"p" * 32,
            )
        )
        session.add(
            ClientEphemeralKey(
                token_hash_id=idle_hash.id, key_index=0, public_key=b"p" * 32
            )
        )
        session.flush()

    cleanup_task.cleanup_idle_tokens()

    with db_module.get_session() as session:
        assert session.scalars(select(ServerEphemeralKey)).all() == []
        assert session.scalars(select(ClientEphemeralKey)).all() == []


def test_cleanup_idle_tokens_attempts_pnba_revoke(_adapter_manager):
    with db_module.get_session() as session:
        idle_token, _ = _make_token(
            session, platform="rmail", proto_id=PNBA, created_days_ago=100
        )
        idle_id = idle_token.id

    cleanup_task.cleanup_idle_tokens()

    assert idle_id not in _remaining_token_ids()
    _adapter_manager.get_pnba_adapter.assert_called_once_with("rmail")


def test_cleanup_idle_tokens_noop_when_nothing_idle(_adapter_manager, caplog):
    with db_module.get_session() as session:
        _make_token(session, platform="gmail", proto_id=OAUTH2, created_days_ago=0)

    caplog.set_level("DEBUG")
    cleanup_task.cleanup_idle_tokens()

    assert "No idle tokens to clean up" in caplog.text
    _adapter_manager.get_oauth2_adapter.assert_not_called()
