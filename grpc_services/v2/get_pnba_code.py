# SPDX-License-Identifier: GPL-3.0-only
"""Get PNBA code gRPC service implementation."""

import grpc

from platforms.adapter_ipc_handler import AdapterIPCHandler
from platforms.adapter_manager import AdapterManager
from protos.v2 import publisher_pb2


def GetPNBACode(self, request, context):
    """Handles Requesting Phone number-based Authentication."""

    response = publisher_pb2.GetPNBACodeResponse

    def validate_fields():
        return self.handle_request_field_validation(
            context, request, response, ["phone_number", "platform"]
        )

    try:
        invalid_fields_response = validate_fields()
        if invalid_fields_response:
            return invalid_fields_response

        adapter = AdapterManager.get_adapter_path(
            name=request.platform.lower(), protocol="pnba"
        )
        if not adapter:
            raise NotImplementedError(
                f"The platform '{request.platform.lower()}' with "
                "protocol 'pnba' is currently not supported. "
                "Please contact the developers for more information on when "
                "this platform will be implemented."
            )

        params = {
            "phone_number": request.phone_number,
            "base_path": adapter["assets_path"],
            "request_identifier": getattr(request, "request_identifier") or None,
        }

        pipe = AdapterIPCHandler.invoke(
            adapter_path=adapter["path"],
            venv_path=adapter["venv_path"],
            method="send_authorization_code",
            params=params,
        )

        if pipe.get("error"):
            return self.handle_create_grpc_error_response(
                context,
                response,
                pipe.get("error"),
                grpc.StatusCode.INVALID_ARGUMENT,
                error_type="UNKNOWN",
            )

        result = pipe.get("result")

        if not result.get("success"):
            return self.handle_create_grpc_error_response(
                context,
                response,
                result.get("message"),
                grpc.StatusCode.INVALID_ARGUMENT,
            )

        return response(success=True, message=result.get("message"))

    except NotImplementedError as e:
        return self.handle_create_grpc_error_response(
            context,
            response,
            str(e),
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
