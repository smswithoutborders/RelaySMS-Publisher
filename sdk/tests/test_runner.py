# SPDX-License-Identifier: GPL-3.0-only

import asyncio
import io
import json

import pytest

from relaysms_adapter_sdk import (
    Account,
    AuthorizationRequest,
    AuthorizationUrl,
    CodeExchangeRequest,
    OAuth2Adapter,
    RevokeRequest,
    SendRequest,
    TokenInvalidError,
    wire,
)
from relaysms_adapter_sdk.errors import (
    INTERNAL_ERROR,
    INVALID_PARAMS,
    METHOD_NOT_FOUND,
    PARSE_ERROR,
)
from relaysms_adapter_sdk.runner import handle, run


class FakeAdapter(OAuth2Adapter):
    def __init__(self):
        self.revoked = []

    def create_authorization_url(self, request: AuthorizationRequest):
        return AuthorizationUrl(url="https://auth", state=request.state)

    async def exchange_code(self, request: CodeExchangeRequest):
        if request.code == "boom":
            raise RuntimeError("secret detail")
        return Account(identifier="me", token={"access_token": request.code})

    def send_message(self, request: SendRequest):
        raise TokenInvalidError("Token expired.")

    def revoke(self, request: RevokeRequest):
        self.revoked.append(request.account.identifier)

    def helper(self):
        return "not exposed"


def call(adapter, method, params=None, request_id=1):
    line = json.dumps(
        {
            "jsonrpc": "2.0",
            "id": request_id,
            "method": method,
            "params": params or {},
        }
    )
    return json.loads(handle(adapter, line))


@pytest.fixture
def adapter():
    return FakeAdapter()


class TestHandle:
    def test_result(self, adapter):
        response = call(adapter, "create_authorization_url", {"state": "s"}, 9)
        assert response == {
            "jsonrpc": "2.0",
            "id": 9,
            "result": {
                "url": "https://auth",
                "state": "s",
                "code_verifier": None,
                "client_id": None,
                "scope": None,
                "redirect_url": None,
            },
        }

    def test_async_method(self, adapter):
        response = call(adapter, "exchange_code", {"code": "c"})
        assert response["result"] == {
            "identifier": "me",
            "token": {"access_token": "c"},
            "name": None,
        }

    def test_none_result(self, adapter):
        response = call(adapter, "revoke", {"account": {"identifier": "me"}})
        assert response["result"] is None
        assert adapter.revoked == ["me"]

    def test_adapter_error(self, adapter):
        response = call(adapter, "send_message", {"message": {"body": "hi"}})
        assert response["error"] == {
            "code": TokenInvalidError.code,
            "message": "Token expired.",
        }

    def test_unexpected_error_hides_details(self, adapter, caplog):
        response = call(adapter, "exchange_code", {"code": "boom"})
        assert response["error"]["code"] == INTERNAL_ERROR
        assert "secret" not in response["error"]["message"]
        assert "secret detail" in caplog.text

    def test_invalid_params(self, adapter):
        response = call(adapter, "exchange_code", {})
        assert response["error"]["code"] == INVALID_PARAMS

    @pytest.mark.parametrize("method", ["helper", "__init__", "send_code"])
    def test_only_protocol_methods(self, adapter, method):
        response = call(adapter, method)
        assert response["error"]["code"] == METHOD_NOT_FOUND

    def test_parse_error(self, adapter):
        response = json.loads(handle(adapter, "not json"))
        assert response["id"] is None
        assert response["error"]["code"] == PARSE_ERROR


def test_run_answers_each_line(adapter):
    request = '{"jsonrpc":"2.0","id":%d,"method":"revoke","params":%s}\n'
    stdin = io.StringIO(
        request % (1, '{"account":{"identifier":"a"}}')
        + "\n"
        + request % (2, '{"account":{"identifier":"b"}}')
    )
    stdout = io.StringIO()
    run(adapter, stdin, stdout)
    ids = [json.loads(line)["id"] for line in stdout.getvalue().splitlines()]
    assert ids == [1, 2]
    assert adapter.revoked == ["a", "b"]


def test_run_keeps_one_event_loop():
    loops = []

    class LoopAdapter(FakeAdapter):
        async def exchange_code(self, request: CodeExchangeRequest):
            loops.append(asyncio.get_running_loop())
            return Account(identifier="me")

    request = wire.encode_request("exchange_code", {"code": "c"}) + "\n"
    run(LoopAdapter(), io.StringIO(request * 2), io.StringIO())
    assert len(loops) == 2
    assert loops[0] is loops[1]
