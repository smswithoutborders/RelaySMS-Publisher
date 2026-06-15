# SPDX-License-Identifier: GPL-3.0-only
"""ExchangePNBACodeAndStore gRPC service handler."""

import grpc

from db import get_session
from grpc_services.v3.utils import (
    create_token_pools_and_encrypt,
    get_pnba_adapter,
    validate_client_ephemeral_public_keys,
)
from logutils import get_logger
from models.token import create as create_token
from platforms.adapter_ipc_handler import AdapterIPCHandler
from protos.v3 import publisher_pb2

logger = get_logger(__name__)


def ExchangePNBACodeAndStore(self, request, context):
    """Handles ExchangePNBACodeAndStore."""

    response = publisher_pb2.ExchangePNBACodeAndStoreResponse

    _, auth_error = self.handle_v1_request_auth(context, response)
    if auth_error:
        return auth_error

    invalid = self.handle_request_field_validation(
        context,
        request,
        response,
        [
            "platform",
            "phone_number",
            "authorization_code",
            "client_ephemeral_public_keys",
        ],
    )
    if invalid:
        return invalid

    try:
        validation_error = validate_client_ephemeral_public_keys(
            request.client_ephemeral_public_keys
        )
        if validation_error:
            return self.handle_create_grpc_error_response(
                context,
                response,
                validation_error,
                grpc.StatusCode.INVALID_ARGUMENT,
            )

        adapter = get_pnba_adapter(request.platform)

        params = {
            "code": request.authorization_code,
            "phone_number": request.phone_number,
            "base_path": adapter["assets_path"],
            "password": request.password or None,
            "request_identifier": request.request_identifier or None,
        }

        if params.get("password"):
            pipe = AdapterIPCHandler.invoke(
                adapter_path=adapter["path"],
                venv_path=adapter["venv_path"],
                method="validate_password_and_fetch_user_info",
                params=params,
            )
        else:
            pipe = AdapterIPCHandler.invoke(
                adapter_path=adapter["path"],
                venv_path=adapter["venv_path"],
                method="validate_code_and_fetch_user_info",
                params=params,
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
        if result.get("two_step_verification_enabled"):
            return response(
                success=True,
                two_step_verification_enabled=True,
                message="two-steps verification is enabled and a password is required",
            )

        with get_session() as s:
            token = create_token(
                platform=request.platform.lower(),
                token_data={
                    "account_id": result["userinfo"]["account_identifier"],
                    "token": result["userinfo"]["account_identifier"],
                },
                session=s,
            )

            token_ciphertext, kid_index, server_public_keys = (
                create_token_pools_and_encrypt(
                    token_id=token.id,
                    client_ephemeral_public_keys=request.client_ephemeral_public_keys,
                    session=s,
                )
            )

        return response(
            success=True,
            message="Successfully fetched and stored token",
            account_identifier=result["userinfo"]["account_identifier"],
            token_ciphertext=token_ciphertext,
            token_id=token.token_id,
            server_ephemeral_public_keys=server_public_keys,
            key_id=kid_index,
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
