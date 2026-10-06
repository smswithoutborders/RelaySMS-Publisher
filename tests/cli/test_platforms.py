# SPDX-License-Identifier: GPL-3.0-only

import pytest
from click.testing import CliRunner

from publisher import db
from publisher.cli import platforms as platforms_cli
from publisher.models import platform_adapter as platform_adapters
from publisher.models.platform_adapter import OAUTH2, PNBA
from tests.helpers import add_adapter, link_account

pytestmark = pytest.mark.usefixtures("platforms_config")


@pytest.fixture(autouse=True)
def gmail(test_db):
    add_adapter("gmail", OAUTH2)
    link_account("gmail", OAUTH2)


def _adapters():
    with db.get_session() as session:
        return [
            (a.name, a.is_enabled)
            for a in platform_adapters.find(session, include_disabled=True)
        ]


def test_remove_needs_force_while_accounts_are_linked():
    runner = CliRunner()

    refused = runner.invoke(platforms_cli.cli, ["remove", "gmail"])
    assert refused.exit_code == 1
    assert "--force" in refused.output
    assert _adapters() == [("gmail", True)]

    forced = runner.invoke(platforms_cli.cli, ["remove", "gmail", "--force"])
    assert forced.exit_code == 0, forced.output
    assert _adapters() == []


def test_disable_and_enable():
    runner = CliRunner()

    assert runner.invoke(platforms_cli.cli, ["disable", "gmail"]).exit_code == 0
    assert _adapters() == [("gmail", False)]

    assert runner.invoke(platforms_cli.cli, ["enable", "gmail"]).exit_code == 0
    assert _adapters() == [("gmail", True)]


def test_update_reports_each_failure_and_carries_on():
    add_adapter("telegram", PNBA)

    # Neither adapter has a clone on disk.
    result = CliRunner().invoke(platforms_cli.cli, ["update"])

    assert result.exit_code == 1
    assert "gmail-0" in result.output and "telegram-1" in result.output
    assert "not a git clone" in result.output
