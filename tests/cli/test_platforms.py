# SPDX-License-Identifier: GPL-3.0-only

import sys

import pytest
from click.testing import CliRunner
from git import Repo

from publisher import db
from publisher.cli import platforms as platforms_cli
from publisher.models import platform_adapter as platform_adapters
from publisher.models.platform_adapter import OAUTH2, PNBA
from tests.helpers import adapter_repo, add_adapter, commit_manifest, link_account

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


def test_update_reports_each_failure_and_carries_on(tmp_path):
    add_adapter("telegram", PNBA)
    with db.get_session() as session:
        for adapter in platform_adapters.find(session, include_disabled=True):
            adapter.source_url = str(tmp_path / "gone" / adapter.name)

    result = _run("update")

    assert result.exit_code == 1
    assert "gmail-0" in result.output and "telegram-1" in result.output
    assert "Listing the tags" in result.output


def _run(*args):
    return CliRunner().invoke(platforms_cli.cli, list(args))


def test_add_list_and_import(tmp_path):
    url = str(adapter_repo(tmp_path / "src" / "mastodon", "mastodon").working_tree_dir)

    added = _run("add", url)
    assert added.exit_code == 0, added.output
    assert "Adapter 'mastodon' added at v1.0.0" in added.output

    source = adapter_repo(tmp_path / "src" / "telegram", "telegram", PNBA)
    Repo.clone_from(str(source.working_tree_dir), tmp_path / "adapters" / "tg-id")
    imported = _run("import")
    assert imported.output.strip() == "Imported 1 adapter(s). telegram"

    listed = _run("list")
    names = [line.split("|")[2].strip() for line in listed.output.splitlines()[2:]]
    assert names == ["gmail", "mastodon", "telegram"]


@pytest.mark.parametrize(
    "args, error",
    [
        (["remove", "nope"], "No registered adapter"),
        (["disable", "gmail"], "Multiple matches"),
    ],
)
def test_commands_need_exactly_one_match(args, error):
    add_adapter("gmail", PNBA)

    result = _run(*args)

    assert result.exit_code == 2
    assert error in result.output


def test_exec_runs_the_adapter_cli_in_its_venv(tmp_path):
    adapter_dir = tmp_path / "adapters" / "gmail-0"
    adapter_dir.mkdir(parents=True)
    (adapter_dir / "cli.py").write_text("import sys; sys.exit(int(sys.argv[1]))")
    (tmp_path / "venvs" / "gmail-0" / "bin").mkdir(parents=True)
    (tmp_path / "venvs" / "gmail-0" / "bin" / "python3").symlink_to(sys.executable)

    assert _run("exec", "gmail", "--", "3").exit_code == 3


def test_add_and_update_take_a_version(tmp_path):
    repo = adapter_repo(tmp_path / "src", "mastodon", OAUTH2, tag="v1.0.0")
    commit_manifest(repo, "mastodon", OAUTH2, tag="v1.1.0")
    commit_manifest(repo, "mastodon", OAUTH2, tag="v2.0.0")

    assert (
        "at v1.1.0" in _run("add", str(repo.working_tree_dir), "--tag", "v1.1.0").output
    )
    updated = _run("update", "mastodon")

    assert updated.exit_code == 0, updated.output
    assert "Updated 'mastodon' to v2.0.0" in updated.output


@pytest.mark.parametrize(
    "args, error",
    [
        (["add", "url", "--tag", "v1.0.0", "--branch"], "either --tag or --branch"),
        (["update", "--tag", "v1.0.0"], "--tag needs an adapter name"),
    ],
)
def test_version_flags_are_checked(args, error):
    result = _run(*args)

    assert result.exit_code == 2
    assert error in result.output
