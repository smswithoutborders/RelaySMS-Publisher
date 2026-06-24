# SPDX-License-Identifier: GPL-3.0-only
"""GetPNBACode gRPC service handler."""

import grpc

from grpc_services.v3.utils import get_pnba_adapter
from logutils import get_logger
from platforms.adapter_ipc_handler import AdapterIPCHandler
from protos.v3 import publisher_pb2

logger = get_logger(__name__)


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
        adapter = get_pnba_adapter(self.adapter_manager, request.platform)

        pipe = AdapterIPCHandler.invoke(
            adapter_path=adapter.path,
            venv_path=adapter.venv_path,
            method="send_authorization_code",
            params={
                "phone_number": request.phone_number,
                "base_path": adapter.assets_path,
                "request_identifier": request.request_identifier or None,
            },
        )

        if pipe.get("error"):
            return self.handle_create_grpc_error_response(
                context,
                response,
                pipe["error"],
                grpc.StatusCode.INVALID_ARGUMENT,
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

        return response(success=True, message=result.get("message"))

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
