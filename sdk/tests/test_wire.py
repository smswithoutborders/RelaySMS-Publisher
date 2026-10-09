# SPDX-License-Identifier: GPL-3.0-only

import json
from datetime import UTC, datetime

import pytest

from relaysms_adapter_sdk import wire
from relaysms_adapter_sdk.errors import (
    INVALID_REQUEST,
    PARSE_ERROR,
    AdapterError,
    InvalidParamsError,
    RateLimitedError,
    TokenInvalidError,
)
from relaysms_adapter_sdk.types import (
    Account,
    Attachment,
    CodeSent,
    Message,
    SendRequest,
)


class TestRequests:
    def test_round_trip(self):
        line = wire.encode_request("revoke", {"account": {"identifier": "a"}}, 7)
        request = wire.parse_request(line)
        assert request == wire.Request(7, "revoke", {"account": {"identifier": "a"}})

    def test_params_default_to_empty(self):
        request = wire.parse_request('{"jsonrpc":"2.0","id":1,"method":"m"}')
        assert request.params == {}

    def test_bad_json(self):
        with pytest.raises(AdapterError) as e:
            wire.parse_request("{")
        assert e.value.code == PARSE_ERROR

    @pytest.mark.parametrize(
        "message",
        [
            [],
            {"id": 1, "method": "m"},
            {"jsonrpc": "2.0", "method": "m"},
            {"jsonrpc": "2.0", "id": True, "method": "m"},
            {"jsonrpc": "2.0", "id": 1, "method": 3},
            {"jsonrpc": "2.0", "id": 1, "method": "m", "params": [1]},
        ],
    )
    def test_invalid_request(self, message):
        with pytest.raises(AdapterError) as e:
            wire.parse_request(json.dumps(message))
        assert e.value.code == INVALID_REQUEST


class TestResponses:
    def test_result(self):
        line = wire.encode_result(1, CodeSent(message="ok"))
        assert wire.parse_response(line) == {"expires_at": None, "message": "ok"}

    def test_error_keeps_its_class(self):
        line = wire.encode_error(1, TokenInvalidError("expired"))
        with pytest.raises(TokenInvalidError, match="expired"):
            wire.parse_response(line)

    def test_rate_limit_keeps_retry_after(self):
        line = wire.encode_error(1, RateLimitedError("slow down", retry_after=30))
        with pytest.raises(RateLimitedError) as e:
            wire.parse_response(line)
        assert e.value.retry_after == 30

    def test_unknown_code(self):
        line = wire.encode_error(1, AdapterError("odd", code=-32099))
        with pytest.raises(AdapterError) as e:
            wire.parse_response(line)
        assert type(e.value) is AdapterError
        assert e.value.code == -32099

    @pytest.mark.parametrize(
        "line",
        ['{"id":1,"result":1}', '{"jsonrpc":"2.0","id":1,"error":{"code":"x"}}'],
    )
    def test_invalid_response(self, line):
        with pytest.raises(AdapterError, match="Invalid JSON-RPC"):
            wire.parse_response(line)


class TestConversion:
    def test_round_trip(self):
        request = SendRequest(
            message=Message(
                body="hi",
                recipient="+237",
                attachments=(Attachment(b"\x00\x01", "a.bin", "x/y"),),
            ),
            account=Account("me", token={"t": 1}),
        )
        assert wire.from_json(SendRequest, wire.to_json(request)) == request

    def test_datetime(self):
        sent = CodeSent(expires_at=datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC))
        assert wire.to_json(sent)["expires_at"] == "2026-01-02T03:04:05+00:00"
        assert wire.from_json(CodeSent, wire.to_json(sent)) == sent

    def test_ignores_unknown_fields(self):
        message = wire.from_json(Message, {"body": "hi", "cc": ["x"]})
        assert message == Message(body="hi")

    def test_null_optional(self):
        request = wire.from_json(
            SendRequest, {"message": {"body": "b"}, "account": None}
        )
        assert request.account is None

    @pytest.mark.parametrize(
        ("data", "error"),
        [
            ({}, r"SendRequest\.message is required"),
            ({"message": "hi"}, r"SendRequest\.message must be an object"),
            ({"message": {"body": 1}}, r"message\.body must be str"),
            (
                {"message": {"body": "b", "attachments": {}}},
                r"attachments must be a list",
            ),
            (
                {
                    "message": {
                        "body": "b",
                        "attachments": [
                            {"data": "!!", "filename": "f", "mimetype": "m"}
                        ],
                    }
                },
                r"attachments\[0\]\.data must be base64",
            ),
            (
                {"message": {"body": "b"}, "account": {"identifier": "a", "token": 1}},
                r"account\.token must be dict",
            ),
        ],
    )
    def test_invalid(self, data, error):
        with pytest.raises(InvalidParamsError, match=error):
            wire.from_json(SendRequest, data)

    def test_bool_is_not_str_or_int(self):
        with pytest.raises(InvalidParamsError, match="must be str"):
            wire.from_json(Account, {"identifier": True})

    def test_bad_datetime(self):
        with pytest.raises(InvalidParamsError, match="ISO 8601"):
            wire.from_json(CodeSent, {"expires_at": "soon"})
