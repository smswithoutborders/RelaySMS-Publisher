# SPDX-License-Identifier: GPL-3.0-only
"""Runs the example adapter the way the Publisher does, in its own process."""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from relaysms_adapter_sdk import wire
from relaysms_adapter_sdk.errors import (
    METHOD_NOT_FOUND,
    AdapterError,
    AuthenticationError,
)
from relaysms_adapter_sdk.paths import CONFIG_DIR_ENV, STATE_DIR_ENV

SDK = Path(__file__).parents[1]


@pytest.fixture
def env(tmp_path):
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "credentials.json").write_text('{"code": "123456"}')
    return {
        **os.environ,
        "PYTHONPATH": os.pathsep.join(
            [
                str(SDK / "src"),
                str(SDK / "examples" / "echo-adapter" / "src"),
            ]
        ),
        CONFIG_DIR_ENV: str(tmp_path / "config"),
        STATE_DIR_ENV: str(tmp_path / "state"),
    }


def invoke(env, *requests, entry="echo_adapter:EchoAdapter"):
    process = subprocess.run(
        [sys.executable, "-m", "relaysms_adapter_sdk", entry],
        input="".join(
            wire.encode_request(m, p, i) + "\n" for i, (m, p) in enumerate(requests)
        ),
        capture_output=True,
        text=True,
        env=env,
        timeout=30,
        check=False,
    )
    return process


def test_link_and_send(env, tmp_path):
    process = invoke(
        env,
        ("send_code", {"phone_number": "+237"}),
        ("verify_code", {"phone_number": "+237", "code": "123456"}),
        (
            "send_message",
            {
                "account": {"identifier": "+237"},
                "message": {"body": "hi"},
            },
        ),
    )
    assert process.returncode == 0
    responses = [wire.parse_response(line) for line in process.stdout.splitlines()]
    assert responses[1] == {
        "identifier": "+237",
        "token": {"number": "+237"},
        "name": None,
    }
    outbox = (tmp_path / "state" / "outbox.jsonl").read_text()
    assert json.loads(outbox) == {"from": "+237", "body": "hi"}
    logs = [json.loads(line) for line in process.stderr.splitlines()]
    assert {
        "level": "INFO",
        "logger": "echo_adapter.adapter",
        "message": "Code for +237 is 123456",
    } in logs


def test_wrong_code(env):
    process = invoke(env, ("verify_code", {"phone_number": "+237", "code": "0"}))
    with pytest.raises(AuthenticationError):
        wire.parse_response(process.stdout)


def test_no_password_step(env):
    process = invoke(
        env, ("verify_password", {"phone_number": "+237", "password": "p"})
    )
    with pytest.raises(AdapterError, match="no two-step passwords") as e:
        wire.parse_response(process.stdout)
    assert e.value.code == METHOD_NOT_FOUND


@pytest.mark.parametrize("entry", ["echo_adapter:Missing", "json:JSONDecoder"])
def test_bad_entry(env, entry):
    process = invoke(env, entry=entry)
    assert process.returncode == 1
    assert "Could not start" in process.stderr


def test_usage(env):
    process = subprocess.run(
        [sys.executable, "-m", "relaysms_adapter_sdk"],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )
    assert process.returncode == 2
    assert "usage:" in process.stderr
