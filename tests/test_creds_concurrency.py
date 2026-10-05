# SPDX-License-Identifier: GPL-3.0-only
"""Each test reads, commits a change from a nested session, then writes stale."""

import datetime

import pytest
from argon2 import PasswordHasher

from publisher.db import get_session
from publisher.models import credential as credentials
from publisher.models import credential_session as credential_sessions
from publisher.models.credential import (
    ALL_SCOPES,
    CredentialConflictError,
    CredentialScope,
)
from publisher.models.credential_session import CredentialSession
from tests.creds_fixtures import *  # noqa: F403
from tests.creds_fixtures import USERNAME, can_log_in, create_credential

MAX_AGE = datetime.timedelta(hours=1)


class ResettingHasher(PasswordHasher):
    """Has a reset commit while the first rehash is being computed."""

    resetting = False
    reset_password: str | None = None

    def hash(self, password, *, salt=None):
        # The reset hashes its new password too, which must not reset again.
        if not self.resetting:
            self.resetting = True
            with get_session() as other:
                self.reset_password = credentials.reset_password(
                    other, credentials.get_or_raise(other, USERNAME)
                )
        return super().hash(password, salt=salt)


def test_rehash_does_not_undo_a_concurrent_reset(monkeypatch):
    old_password = create_credential(USERNAME)
    hasher = ResettingHasher(time_cost=2, memory_cost=1024, parallelism=1)
    monkeypatch.setattr(credentials, "password_hasher", hasher)

    with get_session() as db:
        assert credentials.authenticate(db, USERNAME, old_password) is not None

    assert not can_log_in(USERNAME, old_password)
    assert hasher.reset_password is not None
    assert can_log_in(USERNAME, hasher.reset_password)


def test_login_racing_a_reset_gets_no_working_session():
    password = create_credential(USERNAME)

    with get_session() as db:
        credential = credentials.authenticate(db, USERNAME, password)
        with get_session() as other:
            credentials.reset_password(other, credentials.get_or_raise(other, USERNAME))
        _, token = credential_sessions.create(db, credential, max_age=MAX_AGE)

    with get_session() as db:
        assert credential_sessions.get_active(db, token) is None


def test_login_racing_a_delete_gets_no_working_session():
    password = create_credential(USERNAME)

    with get_session() as db:
        credential = credentials.authenticate(db, USERNAME, password)
        with get_session() as other:
            credentials.delete(other, credentials.get_or_raise(other, USERNAME))
        _, token = credential_sessions.create(db, credential, max_age=MAX_AGE)

    create_credential(USERNAME)

    with get_session() as db:
        assert credential_sessions.get_active(db, token) is None


def test_orm_delete_cascades_to_sessions_and_scopes():
    create_credential(USERNAME)
    with get_session() as db:
        credential = credentials.get_or_raise(db, USERNAME)
        credential_sessions.create(db, credential, max_age=MAX_AGE)

    with get_session() as db:
        credentials.delete(db, credentials.get_or_raise(db, USERNAME))

    with get_session() as db:
        assert db.query(CredentialSession).count() == 0
        assert db.query(CredentialScope).count() == 0


def test_revoked_actor_cannot_finish_a_concurrent_change():
    create_credential("alice")
    create_credential("bob")

    with get_session() as db:
        # Bob authenticated before alice revoked him.
        bob = credentials.get_or_raise(db, "bob")
        with get_session() as other:
            alice = credentials.get_or_raise(other, "alice")
            credentials.update(
                other,
                credentials.get_or_raise(other, "bob"),
                scopes=["stats:publications:read"],
                actor=alice,
            )

        with pytest.raises(CredentialConflictError):
            credentials.create(db, "backdoor", ALL_SCOPES, actor=bob)

    with get_session() as db:
        assert credentials.get_by_username(db, "backdoor") is None


def test_concurrent_mutual_demotion_lets_only_one_win():
    create_credential("alice")
    create_credential("bob")

    with get_session() as alice_db:
        alice = credentials.get_or_raise(alice_db, "alice")
        with get_session() as bob_db:
            bob = credentials.get_or_raise(bob_db, "bob")
            credentials.update(
                bob_db,
                credentials.get_or_raise(bob_db, "alice"),
                scopes=["stats:publications:read"],
                actor=bob,
            )

        with pytest.raises(CredentialConflictError):
            credentials.update(
                alice_db,
                credentials.get_or_raise(alice_db, "bob"),
                scopes=["stats:publications:read"],
                actor=alice,
            )

    with get_session() as db:
        assert credentials.get_or_raise(db, "bob").is_administrator
