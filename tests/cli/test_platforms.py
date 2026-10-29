# SPDX-License-Identifier: GPL-3.0-only

import json
from pathlib import Path

import pytest
from click.testing import CliRunner

from publisher import db
from publisher.cli import platforms as platforms_cli
from publisher.models import platform_adapter as platform_adapters
from publisher.models.platform_adapter import OAUTH2, PNBA
from tests.helpers import (
    adapter_repo,
    add_adapter,
    add_adapter_with_manifest,
    commit_manifest,
    link_account,
)

pytestmark = pytest.mark.usefixtures("platforms_config", "fake_adapter_build")


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


def test_add_and_list(tmp_path):
    url = str(adapter_repo(tmp_path / "src" / "mastodon", "mastodon").working_tree_dir)

    added = _run("add", url)
    assert added.exit_code == 0, added.output
    assert "Adapter 'mastodon' added at v1.0.0" in added.output

    listed = _run("list")
    names = [line.split("|")[2].strip() for line in listed.output.splitlines()[2:]]
    assert names == ["gmail", "mastodon"]


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


def test_exec_runs_a_venv_command_with_the_adapter_dirs(tmp_path):
    (tmp_path / "adapters" / "gmail-0").mkdir(parents=True)
    bin_dir = tmp_path / "venvs" / "gmail-0" / "bin"
    bin_dir.mkdir(parents=True)
    script = bin_dir / "gmail-admin"
    script.write_text(
        "#!/bin/sh\n"
        f'[ "$RELAYSMS_ADAPTER_CONFIG_DIR" = "{tmp_path}/config/gmail-0" ] || exit 9\n'
        f'[ "$RELAYSMS_ADAPTER_STATE_DIR" = "{tmp_path}/state/gmail-0" ] || exit 9\n'
        'exit "$1"\n'
    )
    script.chmod(0o755)

    assert _run("exec", "gmail", "--", "gmail-admin", "3").exit_code == 3


@pytest.mark.parametrize("command", ["missing", "../../bin/sh"])
def test_exec_runs_only_venv_commands(tmp_path, command):
    (tmp_path / "venvs" / "gmail-0" / "bin").mkdir(parents=True)

    result = _run("exec", "gmail", "--", command)

    assert result.exit_code == 1
    assert "has no command" in result.output


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


def test_update_with_a_tag_needs_an_adapter_name():
    result = _run("update", "--tag", "v1.0.0")

    assert result.exit_code == 2
    assert "--tag needs an adapter name" in result.output


RMAIL_MANIFEST = """
entry = "rmail:Adapter"
name = "rmail"
display_name = "RelaySMS Mail"
protocol = "pnba"
category = "email"

[config.smtp_host]
required = true

[config.smtp_port]
type = "integer"

[config.smtp_password]
secret = true

[setup.client_file]
type = "file"
required = true
"""


@pytest.fixture
def rmail():
    adapter = add_adapter_with_manifest("rmail", PNBA, RMAIL_MANIFEST)
    return Path(adapter.config_path) / "credentials.json"


def test_config_set_asks_for_bare_keys_without_echoing(rmail):
    result = CliRunner().invoke(
        platforms_cli.cli,
        [
            "config",
            "set",
            "rmail",
            "SMTP_HOST=smtp.example",
            "smtp_port=465",
            "smtp_password",
        ],
        input="hunter2\n",
    )

    assert result.exit_code == 0, result.output
    assert "hunter2" not in result.output
    assert json.loads(rmail.read_text()) == {
        "smtp_host": "smtp.example",
        "smtp_port": 465,
        "smtp_password": "hunter2",
    }


def test_config_show_hides_secrets_and_unset_removes(rmail):
    rmail.parent.mkdir(parents=True)
    rmail.write_text('{"smtp_host": "smtp.example", "smtp_password": "hunter2"}')
    runner = CliRunner()

    shown = runner.invoke(platforms_cli.cli, ["config", "show", "rmail"]).output
    assert "smtp.example" in shown
    assert "(secret, set)" in shown
    assert "hunter2" not in shown

    result = runner.invoke(
        platforms_cli.cli, ["config", "set", "rmail", "--unset", "smtp_password"]
    )
    assert result.exit_code == 0, result.output
    assert json.loads(rmail.read_text()) == {"smtp_host": "smtp.example"}


def test_config_set_refuses_values_of_the_wrong_type(rmail):
    result = CliRunner().invoke(
        platforms_cli.cli, ["config", "set", "rmail", "smtp_port=25a"]
    )

    assert result.exit_code == 1
    assert "smtp_port must be a whole number" in result.output
    assert not rmail.exists()


@pytest.mark.parametrize("given", ["--input", None])
def test_setup_reads_file_inputs(rmail, adapter_calls, tmp_path, given):
    (tmp_path / "client.json").write_text('{"web": {}}')
    adapter_calls.results["setup"] = {"settings": {"smtp_host": "h"}}
    if given:
        args, answers = ["--input", f"client_file=@{tmp_path}/client.json"], None
    else:
        args, answers = [], f"{tmp_path}/client.json\n"

    result = CliRunner().invoke(
        platforms_cli.cli, ["setup", "rmail", *args], input=answers
    )

    assert result.exit_code == 0, result.output
    [(_, _, request)] = adapter_calls.calls
    assert request.inputs == {"client_file": '{"web": {}}'}
    assert json.loads(rmail.read_text()) == {"smtp_host": "h"}
