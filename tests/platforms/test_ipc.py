# SPDX-License-Identifier: GPL-3.0-only
"""Calls into a real adapter process built on the SDK."""

import logging
import sys

import pytest

from publisher.models.platform_adapter import PlatformAdapter
from publisher.platforms import ipc
from relaysms_adapter_sdk import (
    Account,
    AdapterError,
    AuthorizationRequest,
    CodeExchangeRequest,
    InvalidParamsError,
    Message,
    RevokeRequest,
    SendRequest,
)
from relaysms_adapter_sdk.errors import INTERNAL_ERROR

ADAPTER = """
import logging, os, sys

from relaysms_adapter_sdk import (
    AuthorizationUrl, InvalidParamsError, OAuth2Adapter, SendResult,
)


class Fake(OAuth2Adapter):
    def create_authorization_url(self, request):
        logging.getLogger("fake").warning("careful")
        return AuthorizationUrl(url="https://auth", state=request.state)

    def exchange_code(self, request):
        raise InvalidParamsError("bad code")

    def send_message(self, request):
        return SendResult(token=dict(os.environ))

    def revoke(self, request):
        sys.exit(3)
"""


@pytest.fixture
def adapter(platforms_config, tmp_path):
    """An installed adapter whose venv runs this interpreter."""
    adapter = PlatformAdapter(id="fake-0", name="fake")
    code = tmp_path / "adapters" / "fake-0"
    code.mkdir(parents=True)
    (code / "adapter.toml").write_text(
        'entry = "fake_adapter:Fake"\nname = "fake"\ndisplay_name = "Fake"\n'
        'protocol = "oauth2"\ncategory = "text"\n'
    )
    (code / "fake_adapter.py").write_text(ADAPTER)
    python = tmp_path / "venvs" / "fake-0" / "bin" / "python"
    python.parent.mkdir(parents=True)
    python.write_text(f'#!/bin/sh\nexec "{sys.executable}" "$@"\n')
    python.chmod(0o755)
    return adapter


def test_the_result_comes_back(adapter):
    result = ipc.call(adapter, "create_authorization_url", AuthorizationRequest("s"))

    assert (result["url"], result["state"]) == ("https://auth", "s")


def test_adapter_errors_keep_their_type(adapter):
    with pytest.raises(InvalidParamsError, match="bad code"):
        ipc.call(adapter, "exchange_code", CodeExchangeRequest(code="c"))


def test_a_crashing_adapter_is_an_internal_error(adapter):
    with pytest.raises(AdapterError, match="exited with code 3") as e:
        ipc.call(adapter, "revoke", RevokeRequest(Account("me")))

    assert e.value.code == INTERNAL_ERROR


def test_adapter_log_lines_keep_their_level(adapter, caplog):
    caplog.set_level(logging.DEBUG, logger=ipc.__name__)

    ipc.call(adapter, "create_authorization_url", AuthorizationRequest())

    [record] = [r for r in caplog.records if "careful" in r.getMessage()]
    assert record.levelno == logging.WARNING
    assert record.getMessage() == "[fake] fake: careful"


def test_adapters_get_their_dirs_but_not_the_publisher_secrets(adapter, tmp_path):
    env = ipc.call(adapter, "send_message", SendRequest(Message(body="hi")))["token"]

    assert env["RELAYSMS_ADAPTER_CONFIG_DIR"] == str(tmp_path / "config" / "fake-0")
    assert env["RELAYSMS_ADAPTER_STATE_DIR"] == str(tmp_path / "state" / "fake-0")
    assert "DATA_ENCRYPTION_KEY" not in env


def test_an_adapter_without_a_manifest_is_an_internal_error(adapter, tmp_path):
    (tmp_path / "adapters" / "fake-0" / "adapter.toml").unlink()

    with pytest.raises(AdapterError, match=r"adapter\.toml") as e:
        ipc.call(adapter, "revoke", RevokeRequest(Account("me")))

    assert e.value.code == INTERNAL_ERROR
