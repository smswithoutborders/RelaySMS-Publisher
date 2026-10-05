# SPDX-License-Identifier: GPL-3.0-only
"""GetPNBACode handler."""

import logging
from datetime import datetime

from grpc_interceptor.exceptions import InvalidArgument

from grpc_services.utils import call_adapter, require_fields
from platforms.adapter_manager import AdapterManager
from protos.v3 import publisher_pb2

logger = logging.getLogger(__name__)


def _to_epoch_seconds(value):
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return int(value)
    try:
        return int(
            datetime.fromisoformat(str(value).replace("Z", "+00:00")).timestamp()
        )
    except ValueError:
        logger.warning("Ignoring unparseable expires_at %r.", value)
        return None


def get_pnba_code(
    request, adapter_manager: AdapterManager
) -> publisher_pb2.GetPNBACodeResponse:
    require_fields(request, "phone_number", "platform")

    adapter = adapter_manager.get_pnba_adapter(request.platform)
    result = call_adapter(
        adapter,
        "send_authorization_code",
        {
            "phone_number": request.phone_number,
            "base_path": adapter.assets_path,
            "request_identifier": request.request_identifier or None,
            "channel": request.channel or None,
        },
    )
    if not result.get("success"):
        raise InvalidArgument(result.get("message"))

    response = publisher_pb2.GetPNBACodeResponse(
        success=True, message=result.get("message")
    )
    expires_at = _to_epoch_seconds(result.get("expires_at"))
    if expires_at is not None:
        response.expires_at = expires_at
    return response
