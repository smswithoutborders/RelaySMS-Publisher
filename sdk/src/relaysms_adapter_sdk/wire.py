# SPDX-License-Identifier: GPL-3.0-only
"""JSON-RPC 2.0 messages between the Publisher and an adapter, one per line."""

import base64
import binascii
import dataclasses
import json
import types
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Union, get_args, get_origin, get_type_hints

from relaysms_adapter_sdk.errors import (
    INTERNAL_ERROR,
    INVALID_REQUEST,
    PARSE_ERROR,
    AdapterError,
    InvalidParamsError,
    from_code,
)

VERSION = "2.0"


@dataclass(frozen=True)
class Request:
    id: int | str
    method: str
    params: dict[str, Any]


def encode_request(method: str, params: Any, request_id: int | str = 1) -> str:
    return _dumps(
        {
            "jsonrpc": VERSION,
            "id": request_id,
            "method": method,
            "params": to_json(params),
        }
    )


def parse_request(line: str) -> Request:
    """Parse one request line.

    Raises:
        AdapterError: With PARSE_ERROR or INVALID_REQUEST, as JSON-RPC requires.
    """
    message = _loads(line)
    request_id = message.get("id")
    method = message.get("method")
    params = message.get("params", {})
    if (
        message.get("jsonrpc") != VERSION
        or not isinstance(request_id, int | str)
        # bool is a subclass of int, but true isn't a valid id.
        or isinstance(request_id, bool)
        or not isinstance(method, str)
        or not isinstance(params, dict)
    ):
        raise AdapterError("Invalid JSON-RPC request.", code=INVALID_REQUEST)
    return Request(request_id, method, params)


def encode_result(request_id: int | str, result: Any) -> str:
    return _dumps({"jsonrpc": VERSION, "id": request_id, "result": to_json(result)})


def encode_error(request_id: int | str | None, error: AdapterError) -> str:
    body: dict[str, Any] = {"code": error.code, "message": error.message}
    if error.data is not None:
        body["data"] = error.data
    return _dumps({"jsonrpc": VERSION, "id": request_id, "error": body})


def parse_response(line: str) -> Any:
    """Return the result of one response line.

    Raises:
        AdapterError: The adapter's error, as its own subclass where one matches.
    """
    message = _loads(line)
    if message.get("jsonrpc") != VERSION:
        raise AdapterError("Invalid JSON-RPC response.", code=INTERNAL_ERROR)
    error = message.get("error")
    if error is None:
        return message.get("result")
    if not isinstance(error, dict) or not isinstance(error.get("code"), int):
        raise AdapterError("Invalid JSON-RPC error.", code=INTERNAL_ERROR)
    raise from_code(error["code"], str(error.get("message", "")), error.get("data"))


def to_json(value: Any) -> Any:
    """Convert dataclasses, bytes (base64) and datetimes (ISO 8601) to JSON values."""
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return {
            field.name: to_json(getattr(value, field.name))
            for field in dataclasses.fields(value)
        }
    if isinstance(value, bytes):
        return base64.b64encode(value).decode()
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, list | tuple):
        return [to_json(item) for item in value]
    if isinstance(value, dict):
        return {key: to_json(item) for key, item in value.items()}
    return value


def from_json[T](cls: type[T], data: Any) -> T:
    """Build a dataclass from JSON, ignoring fields it doesn't have.

    Raises:
        InvalidParamsError: A field is missing or has the wrong type.
    """
    return _convert(cls, data, cls.__name__)


def _convert(tp: Any, value: Any, path: str) -> Any:
    origin = get_origin(tp)
    args = get_args(tp)

    if origin in {Union, types.UnionType}:
        if value is None and types.NoneType in args:
            return None
        (inner,) = (arg for arg in args if arg is not types.NoneType)
        return _convert(inner, value, path)

    if isinstance(tp, type) and dataclasses.is_dataclass(tp):
        if not isinstance(value, dict):
            raise InvalidParamsError(f"{path} must be an object.")
        hints = get_type_hints(tp)
        kwargs = {}
        for field in dataclasses.fields(tp):
            if field.name in value:
                kwargs[field.name] = _convert(
                    hints[field.name], value[field.name], f"{path}.{field.name}"
                )
            elif (
                field.default is dataclasses.MISSING
                and field.default_factory is dataclasses.MISSING
            ):
                raise InvalidParamsError(f"{path}.{field.name} is required.")
        return tp(**kwargs)

    if origin is tuple:
        if not isinstance(value, list):
            raise InvalidParamsError(f"{path} must be a list.")
        return tuple(
            _convert(args[0], item, f"{path}[{i}]") for i, item in enumerate(value)
        )

    if tp is bytes:
        try:
            return base64.b64decode(_expect(str, value, path), validate=True)
        except binascii.Error as e:
            raise InvalidParamsError(f"{path} must be base64.") from e

    if tp is datetime:
        try:
            return datetime.fromisoformat(_expect(str, value, path))
        except ValueError as e:
            raise InvalidParamsError(f"{path} must be an ISO 8601 time.") from e

    if origin is dict:
        return _expect(dict, value, path)

    if origin is not None or tp is Any:
        return value

    return _expect(tp, value, path)


def _expect[T](tp: type[T], value: Any, path: str) -> T:
    # bool is a subclass of int, but true isn't a number here.
    if not isinstance(value, tp) or (tp is not bool and isinstance(value, bool)):
        raise InvalidParamsError(f"{path} must be {tp.__name__}.")
    return value


def _dumps(message: dict[str, Any]) -> str:
    return json.dumps(message, ensure_ascii=False, separators=(",", ":"))


def _loads(line: str) -> dict[str, Any]:
    try:
        message = json.loads(line)
    except json.JSONDecodeError as e:
        raise AdapterError(f"Invalid JSON: {e.msg}", code=PARSE_ERROR) from e
    if not isinstance(message, dict):
        raise AdapterError("Invalid JSON-RPC message.", code=INVALID_REQUEST)
    return message
