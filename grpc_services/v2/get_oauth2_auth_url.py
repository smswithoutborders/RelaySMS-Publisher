# SPDX-License-Identifier: GPL-3.0-only
"""Get OAuth2 Authorization URL gRPC Service Implementation"""

import grpc

from platforms.adapter_ipc_handler import AdapterIPCHandler
from platforms.adapter_manager import AdapterManager
from protos.v2 import publisher_pb2


def GetOAuth2AuthorizationUrl(self, request, context):
    """Handles generating OAuth2 authorization URL"""

    response = publisher_pb2.GetOAuth2AuthorizationUrlResponse

    def validate_fields():
        return self.handle_request_field_validation(
            context, request, response, ["platform"]
        )

    try:
        invalid_fields_response = validate_fields()
        if invalid_fields_response:
            return invalid_fields_response

        adapter = AdapterManager.get_adapter_path(
            name=request.platform.lower(), protocol="oauth2"
        )
        if not adapter:
            raise NotImplementedError(
                f"The platform '{request.platform.lower()}' with "
                "protocol 'oauth2' is currently not supported. "
                "Please contact the developers for more information on when "
                "this platform will be implemented."
            )

        params = {
            "state": getattr(request, "state") or None,
            "code_verifier": getattr(request, "code_verifier") or None,
            "autogenerate_code_verifier": getattr(
                request, "autogenerate_code_verifier"
            ),
            "redirect_url": getattr(request, "redirect_url") or None,
            "request_identifier": getattr(request, "request_identifier") or None,
            "base_path": adapter["assets_path"],
        }

        pipe = AdapterIPCHandler.invoke(
            adapter_path=adapter["path"],
            venv_path=adapter["venv_path"],
            method="get_authorization_url",
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

        return response(
            authorization_url=result.get("authorization_url"),
            state=result.get("state"),
            code_verifier=result.get("code_verifier"),
            client_id=result.get("client_id"),
            scope=result.get("scope"),
            redirect_url=result.get("redirect_url"),
            message="Successfully generated authorization url",
        )

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
