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
    monkeypatch.setattr(console.Prompt, "ask", lambda *a, **k: next(replies))


def account(repo):
    return json.loads((repo / ".relaysms" / "account.json").read_text())


class TestPNBA:
    def test_link_send_revoke(self, tmp_path, monkeypatch, capsys):
        repo = make_repo(tmp_path, ECHO)
        answer(monkeypatch, "+237", "123456")
        assert run(repo, "link") == 0
        assert account(repo)["identifier"] == "+237"
        assert "Code for +237 is 123456" in capsys.readouterr().out

        answer(monkeypatch, "+1", "hello")
        assert run(repo, "send") == 0
        outbox = repo / ".relaysms" / "state" / "outbox.jsonl"
        assert json.loads(outbox.read_text()) == {"from": "+237", "body": "hello"}

        assert run(repo, "revoke") == 0
        assert not (repo / ".relaysms" / "account.json").exists()

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

        monkeypatch.setattr(console.webbrowser, "open", browser)
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
