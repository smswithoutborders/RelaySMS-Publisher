# SPDX-License-Identifier: GPL-3.0-only

import re

import pytest
from click.testing import CliRunner

from publisher import credentials
from publisher.cli import creds as creds_cli
from publisher.db import get_session
from publisher.models.credential import Scope
from tests.helpers import USERNAME, can_log_in, create_credential

pytestmark = pytest.mark.usefixtures("test_db", "fast_hasher")


@pytest.fixture
def runner():
    return CliRunner()


def _password_from(output):
    match = re.search(r"^Password : (\S+)$", output, re.MULTILINE)
    assert match, output
    return match.group(1)


def _scopes(username):
    with get_session() as db:
        return credentials.get_or_raise(db, username).scopes


def test_create_prints_a_working_generated_password(runner):
    result = runner.invoke(
        creds_cli.cli, ["create", "--username", "Ops", "--administrator"]
    )

    assert result.exit_code == 0, result.output
    assert "scopes: administrator" in result.output
    password = _password_from(result.output)
    assert len(password) >= 32
    assert can_log_in(USERNAME, password)
    with get_session() as db:
        stored = credentials.get_by_username(db, USERNAME)
        assert stored.username == USERNAME
        assert stored.is_administrator
        assert password not in stored.password_hash


def test_create_with_scopes(runner):
    result = runner.invoke(
        creds_cli.cli,
        ["create", "--username", "analyst", "--scope", "stats:publications:read"],
    )

    assert result.exit_code == 0, result.output
    assert _scopes("analyst") == {Scope.STATS_PUBLICATIONS_READ}


@pytest.mark.parametrize(
    "args, error",
    [
        (["--username", "analyst"], "--scope at least once"),
        (["--username", "analyst", "--scope", "stats:all"], "Invalid value"),
        (["--username", "ab", "--administrator"], "Invalid username"),
        (
            [
                "--username",
                "analyst",
                "--administrator",
                "--scope",
                "stats:publications:read",
            ],
            "not both",
        ),
    ],
)
def test_create_rejects_bad_input(runner, args, error):
    result = runner.invoke(creds_cli.cli, ["create", *args])

    assert result.exit_code != 0
    assert error in result.output


def test_create_rejects_duplicates_case_insensitively(runner):
    runner.invoke(creds_cli.cli, ["create", "--username", USERNAME, "--administrator"])

    result = runner.invoke(
        creds_cli.cli, ["create", "--username", "OPS", "--administrator"]
    )

    assert result.exit_code != 0
    assert "already exists" in result.output


def test_set_scopes_replaces_scopes(runner):
    create_credential("analyst", ["stats:publications:read"])

    result = runner.invoke(
        creds_cli.cli,
        [
            "set-scopes",
            "--username",
            "analyst",
            "--scope",
            "gc:read",
            "--scope",
            "gc:write",
        ],
    )

    assert result.exit_code == 0, result.output
    assert _scopes("analyst") == {Scope.GC_READ, Scope.GC_WRITE}


def test_list_and_scopes_commands(runner):
    create_credential(USERNAME)
    create_credential(
        "analyst", ["stats:publications:read", "stats:publications:reasons"]
    )

    listed = runner.invoke(creds_cli.cli, ["list"]).output
    assert re.search(r"\| ops\s+\| yes\s+\| administrator ", listed)
    assert re.search(
        r"\| analyst\s+\| yes\s+\| stats:publications:read,stats:publications:reasons ",
        listed,
    )

    scopes = runner.invoke(creds_cli.cli, ["scopes"]).output
    assert all(scope.value in scopes for scope in Scope)


def test_reset_password_replaces_old_password(runner):
    old = create_credential(USERNAME)

    result = runner.invoke(creds_cli.cli, ["reset-password", "--username", USERNAME])

    assert result.exit_code == 0
    new = _password_from(result.output)
    assert new != old
    assert not can_log_in(USERNAME, old)
    assert can_log_in(USERNAME, new)


def test_disable_and_enable(runner):
    password = create_credential(USERNAME)

    assert (
        runner.invoke(creds_cli.cli, ["disable", "--username", USERNAME]).exit_code == 0
    )
    assert not can_log_in(USERNAME, password)

    assert (
        runner.invoke(creds_cli.cli, ["enable", "--username", USERNAME]).exit_code == 0
    )
    assert can_log_in(USERNAME, password)
