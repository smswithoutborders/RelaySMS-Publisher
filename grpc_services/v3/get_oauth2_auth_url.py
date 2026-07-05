# SPDX-License-Identifier: GPL-3.0-only
"""GetOAuth2AuthorizationUrl gRPC service handler."""

import grpc

from logutils import get_logger
from platforms.adapter_ipc_handler import AdapterIPCHandler
from protos.v3 import publisher_pb2

logger = get_logger(__name__)


def GetOAuth2AuthorizationUrl(self, request, context):
    """Handles GetOAuth2AuthorizationUrl."""

    response = publisher_pb2.GetOAuth2AuthorizationUrlResponse

    _, auth_error = self.handle_v1_request_auth(context, response)
    if auth_error:
        return auth_error

    invalid = self.handle_request_field_validation(
        context, request, response, ["platform"]
    )
    if invalid:
        return invalid

    try:
        adapter = self.adapter_manager.get_oauth2_adapter(request.platform)

        pipe = AdapterIPCHandler.invoke(
            adapter_path=adapter.path,
            venv_path=adapter.venv_path,
            method="get_authorization_url",
            params={
                "state": request.state or None,
                "code_verifier": request.code_verifier or None,
                "autogenerate_code_verifier": request.autogenerate_code_verifier,
                "redirect_url": request.redirect_url or None,
                "request_identifier": request.request_identifier or None,
                "base_path": adapter.assets_path,
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

        return response(
            authorization_url=result["authorization_url"],
            state=result.get("state"),
            code_verifier=result.get("code_verifier"),
            client_id=result.get("client_id"),
            scope=result.get("scope"),
            redirect_url=result.get("redirect_url"),
            message="Successfully generated authorization URL",
        )

    except NotImplementedError as exc:
        return self.handle_create_grpc_error_response(
            context,
            response,
            exc,
            grpc.StatusCode.UNIMPLEMENTED,
        )

    except ValueError as exc:
        logger.error("%s", exc)
        return self.handle_create_grpc_error_response(
            context,
            response,
            exc,
            grpc.StatusCode.INTERNAL,
            user_msg="Oops! Something went wrong. Please try again later.",
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
