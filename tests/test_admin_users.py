# SPDX-License-Identifier: GPL-3.0-only

import re

import pytest
from click.testing import CliRunner

import admin_users.cli as admin_cli
from db import get_session
from models import admin_user as admin_users
from tests.admin_fixtures import *  # noqa: F401,F403
from tests.admin_fixtures import ADMIN_EMAIL


@pytest.fixture
def runner():
    return CliRunner()


def _password_from(output):
    match = re.search(r"^Password : (\S+)$", output, re.MULTILINE)
    assert match, output
    return match.group(1)


def _verify(email, password):
    with get_session() as db:
        return admin_users.verify_credentials(db, email, password) is not None


def test_create_prints_a_working_generated_password(runner):
    result = runner.invoke(admin_cli.cli, ["create", "--email", "Admin@Example.org"])

    assert result.exit_code == 0, result.output
    password = _password_from(result.output)
    assert len(password) >= 32
    assert _verify(ADMIN_EMAIL, password)
    with get_session() as db:
        stored = admin_users.get_by_email(db, ADMIN_EMAIL)
        assert stored.email == ADMIN_EMAIL
        assert password not in stored.password_hash


def test_create_rejects_duplicates_case_insensitively(runner):
    runner.invoke(admin_cli.cli, ["create", "--email", ADMIN_EMAIL])

    result = runner.invoke(admin_cli.cli, ["create", "--email", "ADMIN@example.org"])

    assert result.exit_code != 0
    assert "already exists" in result.output


def test_reset_password_replaces_old_password(runner):
    old = _password_from(
        runner.invoke(admin_cli.cli, ["create", "--email", ADMIN_EMAIL]).output
    )

    result = runner.invoke(admin_cli.cli, ["reset-password", "--email", ADMIN_EMAIL])

    assert result.exit_code == 0
    new = _password_from(result.output)
    assert new != old
    assert not _verify(ADMIN_EMAIL, old)
    assert _verify(ADMIN_EMAIL, new)


def test_disable_and_enable(runner):
    password = _password_from(
        runner.invoke(admin_cli.cli, ["create", "--email", ADMIN_EMAIL]).output
    )

    assert (
        runner.invoke(admin_cli.cli, ["disable", "--email", ADMIN_EMAIL]).exit_code == 0
    )
    assert not _verify(ADMIN_EMAIL, password)

    assert (
        runner.invoke(admin_cli.cli, ["enable", "--email", ADMIN_EMAIL]).exit_code == 0
    )
    assert _verify(ADMIN_EMAIL, password)


def test_verify_rehashes_outdated_hash(monkeypatch):
    from argon2 import PasswordHasher

    with get_session() as db:
        _, password = admin_users.create_admin(db, ADMIN_EMAIL)
        old_hash = admin_users.get_by_email(db, ADMIN_EMAIL).password_hash

    monkeypatch.setattr(
        admin_users,
        "password_hasher",
        PasswordHasher(time_cost=2, memory_cost=1024, parallelism=1),
    )
    assert _verify(ADMIN_EMAIL, password)

    with get_session() as db:
        new_hash = admin_users.get_by_email(db, ADMIN_EMAIL).password_hash
    assert new_hash != old_hash and "t=2" in new_hash
