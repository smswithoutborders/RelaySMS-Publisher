# SPDX-License-Identifier: GPL-3.0-only
"""GetPNBACode handler."""

import logging
from datetime import datetime

from protos.v3 import publisher_pb2
from publisher.api.grpc.utils import call_adapter, find_adapter, require_fields
from publisher.models.platform_adapter import PNBA
from relaysms_adapter_sdk import CodeRequest

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


def get_pnba_code(request) -> publisher_pb2.GetPNBACodeResponse:
    require_fields(request, "phone_number", "platform")

    adapter = find_adapter(request.platform, PNBA)
    result = call_adapter(
        adapter,
        "send_code",
        CodeRequest(
            phone_number=request.phone_number,
            channel=request.channel or None,
            request_identifier=request.request_identifier or None,
        ),
    )

    response = publisher_pb2.GetPNBACodeResponse(
        success=True, message=result.get("message") or "Authorization code sent."
    )
    expires_at = _to_epoch_seconds(result.get("expires_at"))
    if expires_at is not None:
        response.expires_at = expires_at
    return response
