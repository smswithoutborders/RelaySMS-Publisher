# SPDX-License-Identifier: GPL-3.0-only

import json

import pytest

from echo_adapter import EchoAdapter
from relaysms_adapter_sdk import (
    Account,
    AuthenticationError,
    CodeVerificationRequest,
    InvalidParamsError,
    Message,
    SendRequest,
)
from relaysms_adapter_sdk.paths import CONFIG_DIR_ENV, STATE_DIR_ENV


@pytest.fixture
def adapter(tmp_path, monkeypatch):
    (tmp_path / "credentials.json").write_text('{"code": "123456"}')
    monkeypatch.setenv(CONFIG_DIR_ENV, str(tmp_path))
    monkeypatch.setenv(STATE_DIR_ENV, str(tmp_path / "state"))
    return EchoAdapter()


def test_verify_code(adapter):
    account = adapter.verify_code(CodeVerificationRequest("+237", "123456"))
    assert account == Account("+237", token={"number": "+237"})


def test_wrong_code(adapter):
    with pytest.raises(AuthenticationError):
        adapter.verify_code(CodeVerificationRequest("+237", "0"))


def test_send_message(adapter, tmp_path):
    adapter.send_message(SendRequest(Message(body="hi"), Account("+237")))
    outbox = (tmp_path / "state" / "outbox.jsonl").read_text()
    assert json.loads(outbox) == {"from": "+237", "body": "hi"}


def test_send_needs_account(adapter):
    with pytest.raises(InvalidParamsError):
        adapter.send_message(SendRequest(Message(body="hi")))
