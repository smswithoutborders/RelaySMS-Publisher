# SPDX-License-Identifier: GPL-3.0-only

import json
import os
import socket
import threading
import time
import urllib.request
from pathlib import Path

import pytest

from relaysms_adapter_sdk import console

SDK = Path(__file__).parents[1]

ECHO = """
entry = "echo_adapter:EchoAdapter"
name = "echo"
display_name = "Echo"
protocol = "pnba"
category = "message"

[config.code]
secret = true

[setup.code]
required = true
secret = true
"""

FAKE_OAUTH2 = """
entry = "fake_oauth2:FakeOAuth2Adapter"
name = "fake"
display_name = "Fake"
protocol = "oauth2"
category = "email"
"""


@pytest.fixture(autouse=True)
def pythonpath(monkeypatch):
    paths = [SDK / "src", SDK / "examples" / "echo-adapter" / "src", SDK / "tests"]
    monkeypatch.setenv("PYTHONPATH", os.pathsep.join(map(str, paths)))


def make_repo(tmp_path, manifest):
    (tmp_path / "adapter.toml").write_text(manifest)
    config = tmp_path / ".relaysms" / "config"
    config.mkdir(parents=True)
    (config / "credentials.json").write_text('{"code": "123456"}')
    return tmp_path


def run(repo, *args):
    return console.main(["--dir", str(repo), *args])


def answer(monkeypatch, *answers):
    replies = iter(answers)
    monkeypatch.setattr("rich.prompt.Prompt.ask", lambda *a, **k: next(replies))


def account(repo):
    return json.loads((repo / ".relaysms" / "account.json").read_text())


class TestPNBA:
    def test_link_send_revoke(self, tmp_path, monkeypatch, capsys):
        repo = make_repo(tmp_path, ECHO)
        answer(monkeypatch, "+237", "123456")
        assert run(repo, "link") == 0
        assert account(repo)["identifier"] == "+237"
        assert "Code sent." in capsys.readouterr().out

        answer(monkeypatch, "+1", "hello")
        assert run(repo, "send") == 0
        outbox = repo / ".relaysms" / "state" / "outbox.jsonl"
        assert json.loads(outbox.read_text()) == {"from": "+237", "body": "hello"}

        assert run(repo, "revoke") == 0
        assert not (repo / ".relaysms" / "account.json").exists()

    @pytest.mark.parametrize("given", [["--input", "CODE=654321"], []])
    def test_setup_replaces_credentials(self, tmp_path, monkeypatch, given):
        repo = make_repo(tmp_path, ECHO)
        credentials = repo / ".relaysms" / "config" / "credentials.json"
        credentials.write_text('{"code": "1", "web": {}}')
        answer(monkeypatch, "654321")

        assert run(repo, "setup", *given) == 0

        assert json.loads(credentials.read_text()) == {"code": "654321"}
        assert credentials.stat().st_mode & 0o777 == 0o600

    def test_setup_asks_for_a_file_by_its_path(self, tmp_path, monkeypatch):
        manifest = ECHO.replace("[setup.code]", '[setup.code]\ntype = "file"')
        repo = make_repo(tmp_path, manifest)
        (tmp_path / "code.txt").write_text("654321")
        answer(monkeypatch, str(tmp_path / "code.txt"))

        assert run(repo, "setup") == 0

        credentials = repo / ".relaysms" / "config" / "credentials.json"
        assert json.loads(credentials.read_text()) == {"code": "654321"}

    def test_setup_refuses_unknown_inputs(self, tmp_path, capsys):
        repo = make_repo(tmp_path, ECHO)
        assert run(repo, "setup", "--input", "code=1", "--input", "colour=red") == 1
        assert "colour isn't a setting" in capsys.readouterr().out

    def test_setup_refuses_settings_not_in_config(self, tmp_path, capsys):
        repo = make_repo(tmp_path, ECHO.replace("[config.code]", "[config.other]"))
        credentials = repo / ".relaysms" / "config" / "credentials.json"

        assert run(repo, "setup", "--input", "code=654321") == 1

        assert "code isn't a setting" in capsys.readouterr().out
        assert json.loads(credentials.read_text()) == {"code": "123456"}

    def test_setup_refuses_incomplete_settings(self, tmp_path, capsys):
        manifest = ECHO + "\n[config.other]\nrequired = true\n"
        repo = make_repo(tmp_path, manifest)

        assert run(repo, "setup", "--input", "code=654321") == 1

        assert "other is required" in capsys.readouterr().out

    def test_config_set_asks_for_bare_keys_and_show_hides_secrets(
        self, tmp_path, monkeypatch, capsys
    ):
        repo = make_repo(tmp_path, ECHO)
        credentials = repo / ".relaysms" / "config" / "credentials.json"
        answer(monkeypatch, "654321")

        assert run(repo, "config", "set", "CODE") == 0
        assert json.loads(credentials.read_text()) == {"code": "654321"}

        capsys.readouterr()
        assert run(repo, "config", "show") == 0
        shown = capsys.readouterr().out
        assert "(secret, set)" in shown
        assert "654321" not in shown

        assert run(repo, "config", "set", "--unset", "code") == 0
        assert json.loads(credentials.read_text()) == {}

    def test_a_broken_credentials_file_is_reported(self, tmp_path, capsys):
        repo = make_repo(tmp_path, ECHO)
        (repo / ".relaysms" / "config" / "credentials.json").write_text("{")
        assert run(repo, "config", "show") == 1
        assert "is invalid" in capsys.readouterr().out

    def test_config_set_refuses_unknown_settings(self, tmp_path, capsys):
        repo = make_repo(tmp_path, ECHO)
        assert run(repo, "config", "set", "colour=red") == 1
        assert "colour isn't a setting" in capsys.readouterr().out

    def test_wrong_code(self, tmp_path, monkeypatch, capsys):
        repo = make_repo(tmp_path, ECHO)
        answer(monkeypatch, "0")
        assert run(repo, "link", "--phone", "+237") == 1
        assert "Wrong code" in capsys.readouterr().out

    def test_send_needs_link(self, tmp_path, capsys):
        repo = make_repo(tmp_path, ECHO)
        assert run(repo, "send", "--to", "x", "--body", "b") == 1
        assert "No linked account" in capsys.readouterr().out


class TestOAuth2:
    def test_catches_local_redirect(self, tmp_path, monkeypatch):
        repo = make_repo(tmp_path, FAKE_OAUTH2)
        with socket.socket() as s:
            s.bind(("127.0.0.1", 0))
            port = s.getsockname()[1]

        def browser(url):
            def visit():
                for _ in range(50):
                    try:
                        urllib.request.urlopen(url, timeout=1).read()
                        return
                    except OSError:
                        time.sleep(0.1)

            threading.Thread(target=visit, daemon=True).start()

        monkeypatch.setattr("webbrowser.open", browser)
        redirect = f"http://127.0.0.1:{port}/cb"
        assert run(repo, "link", "--redirect-url", redirect) == 0
        assert account(repo) == {
            "identifier": "the-code/v1",
            "token": {"n": 1},
            "name": None,
        }

    def test_pasted_redirect(self, tmp_path, monkeypatch):
        repo = make_repo(tmp_path, FAKE_OAUTH2)
        answer(monkeypatch, "https://example.com/cb?code=pasted&state=s1")
        assert run(repo, "link", "--no-browser") == 0
        assert account(repo)["identifier"] == "pasted/v1"

    def test_state_mismatch(self, tmp_path, monkeypatch, capsys):
        repo = make_repo(tmp_path, FAKE_OAUTH2)
        answer(monkeypatch, "https://example.com/cb?code=c&state=other")
        assert run(repo, "link", "--no-browser") == 1
        assert "state doesn't match" in capsys.readouterr().out

    def test_send_saves_refreshed_token(self, tmp_path, monkeypatch):
        repo = make_repo(tmp_path, FAKE_OAUTH2)
        answer(monkeypatch, "https://example.com/cb?code=c&state=s1")
        run(repo, "link", "--no-browser")
        attachment = tmp_path / "a.txt"
        attachment.write_text("hi")
        args = ["--to", "x@y", "--subject", "s", "--body", "b"]
        assert run(repo, "send", *args, "--attach", str(attachment)) == 0
        assert account(repo)["token"] == {"n": 2}


def test_call(tmp_path, capsys):
    repo = make_repo(tmp_path, ECHO)
    assert run(repo, "call", "send_code", '{"phone_number": "+237"}') == 0
    assert '"message": "Code sent."' in capsys.readouterr().out


def test_missing_manifest(tmp_path, capsys):
    assert run(tmp_path, "revoke") == 1
    assert "adapter.toml" in capsys.readouterr().out
