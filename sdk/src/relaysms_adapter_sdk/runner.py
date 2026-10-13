# SPDX-License-Identifier: GPL-3.0-only
"""Answers the Publisher's requests on standard input with the adapter."""

import asyncio
import inspect
import logging
import sys
from collections.abc import Callable, Coroutine
from typing import Any, TextIO

from relaysms_adapter_sdk import wire
from relaysms_adapter_sdk.adapter import Adapter
from relaysms_adapter_sdk.errors import INTERNAL_ERROR, METHOD_NOT_FOUND, AdapterError

logger = logging.getLogger(__name__)

type RunAsync = Callable[[Coroutine[Any, Any, Any]], Any]


def run(adapter: Adapter, stdin: TextIO = sys.stdin, stdout: TextIO = sys.stdout):
    """Answer each request line until standard input closes."""
    # One loop for the process, so async clients can outlive a request.
    with asyncio.Runner() as runner:
        for line in stdin:
            if line.strip():
                stdout.write(handle(adapter, line, runner.run) + "\n")
                stdout.flush()


def handle(adapter: Adapter, line: str, run_async: RunAsync = asyncio.run) -> str:
    """Answer one JSON-RPC request line."""
    try:
        request = wire.parse_request(line)
    except AdapterError as e:
        return wire.encode_error(None, e)

    request_type = adapter.RPC_METHODS.get(request.method)
    if request_type is None:
        error = AdapterError(f"Unknown method: {request.method}", code=METHOD_NOT_FOUND)
        return wire.encode_error(request.id, error)

    try:
        result = getattr(adapter, request.method)(
            wire.from_json(request_type, request.params)
        )
        if inspect.isawaitable(result):
            result = run_async(_wait(result))
    except AdapterError as e:
        logger.warning("%s failed: %s", request.method, e.message)
        return wire.encode_error(request.id, e)
    except Exception:
        logger.exception("%s failed", request.method)
        error = AdapterError("Internal adapter error.", code=INTERNAL_ERROR)
        return wire.encode_error(request.id, error)
    return wire.encode_result(request.id, result)


async def _wait(awaitable):
    return await awaitable
