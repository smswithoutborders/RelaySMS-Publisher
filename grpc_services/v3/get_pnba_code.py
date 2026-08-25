# SPDX-License-Identifier: GPL-3.0-only
"""GetPNBACode gRPC service handler."""

from datetime import datetime

import grpc

from logutils import get_logger
from platforms.adapter_ipc_handler import AdapterIPCHandler
from protos.v3 import publisher_pb2

logger = get_logger(__name__)


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


def GetPNBACode(self, request, context):
    """Handles GetPNBACode."""

    response = publisher_pb2.GetPNBACodeResponse

    _, auth_error = self.handle_v1_request_auth(context, response)
    if auth_error:
        return auth_error

    invalid = self.handle_request_field_validation(
        context, request, response, ["phone_number", "platform"]
    )
    if invalid:
        return invalid

    try:
        adapter = self.adapter_manager.get_pnba_adapter(request.platform)

        pipe = AdapterIPCHandler.invoke(
            adapter_path=adapter.path,
            venv_path=adapter.venv_path,
            method="send_authorization_code",
            params={
                "phone_number": request.phone_number,
                "base_path": adapter.assets_path,
                "request_identifier": request.request_identifier or None,
                "channel": request.channel or None,
            },
        )

        if pipe.get("error"):
            logger.error(
                "Adapter error for platform %r: %s", request.platform, pipe["error"]
            )
            return self.handle_create_grpc_error_response(
                context,
                response,
                pipe["error"],
                grpc.StatusCode.INTERNAL,
                user_msg="Oops! Something went wrong. Please try again later.",
                error_type="UNKNOWN",
            )

        result = pipe["result"]

        if not result.get("success"):
            return self.handle_create_grpc_error_response(
                context,
                response,
                result.get("message"),
                grpc.StatusCode.INVALID_ARGUMENT,
            )

        expires_at = _to_epoch_seconds(result.get("expires_at"))
        message = response(success=True, message=result.get("message"))
        if expires_at is not None:
            message.expires_at = expires_at
        return message

    except NotImplementedError as exc:
        return self.handle_create_grpc_error_response(
            context,
            response,
            exc,
            grpc.StatusCode.UNIMPLEMENTED,
        )

    except Exception as exc:
        return self.handle_create_grpc_error_response(
            context,
            response,
            exc,
            grpc.StatusCode.INTERNAL,
            user_msg="Oops! Something went wrong. Please try again later.",
            error_type="UNKNOWN",
        )
