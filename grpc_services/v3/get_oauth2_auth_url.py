# SPDX-License-Identifier: GPL-3.0-only
"""GetOAuth2AuthorizationUrl gRPC service handler."""

import base64
import secrets

import grpc
from cryptography.hazmat.primitives.asymmetric.x25519 import (
    X25519PrivateKey,
    X25519PublicKey,
)

from grpc_services.v3.utils import get_oauth2_adapter
from lib_relaysms_payload_specs.generated import relaysms_spec_payload as rrs
from logutils import get_logger
from models.server_identity_key import get_private_key
from platforms.adapter_ipc_handler import AdapterIPCHandler
from protos.v3 import publisher_pb2

logger = get_logger(__name__)


def _decode_client_ephemeral_key(ec_pk_b64: str) -> bytes:
    """Decode and validate the client ephemeral public key from base64."""
    ec_pk_bytes = base64.urlsafe_b64decode(ec_pk_b64)
    if len(ec_pk_bytes) != 32:
        raise ValueError("Client ephemeral public key must be 32 bytes")
    X25519PublicKey.from_public_bytes(ec_pk_bytes)  # validates curve point
    return ec_pk_bytes


def _get_server_identity_key(ss_kid: int):
    """Look up a server identity key, raising if absent."""
    ss = get_private_key(ss_kid)
    if not ss:
        raise LookupError(f"Server identity key {ss_kid} not found")
    return ss


def GetOAuth2AuthorizationUrl(self, request, context):
    """Generate and return an encrypted OAuth2 authorization URL."""

    response = publisher_pb2.GetOAuth2AuthorizationUrlResponse

    invalid = self.handle_request_field_validation(
        context, request, response, ["platform"]
    )
    if invalid:
        return invalid

    metadata = dict(context.invocation_metadata())
    ec_pk_b64 = metadata.get("x-public-key")

    if not ec_pk_b64:
        return self.handle_create_grpc_error_response(
            context,
            response,
            "Missing x-public-key header (client ephemeral public key)",
            grpc.StatusCode.INVALID_ARGUMENT,
        )

    try:
        ec_pk_bytes = _decode_client_ephemeral_key(ec_pk_b64)
    except Exception as e:
        return self.handle_create_grpc_error_response(
            context,
            response,
            f"Invalid x-public-key: {e}",
            grpc.StatusCode.INVALID_ARGUMENT,
        )

    try:
        ss_kid = secrets.randbelow(256)
        ss = _get_server_identity_key(ss_kid)

        adapter = get_oauth2_adapter(request.platform)

        es = X25519PrivateKey.generate()
        es_bytes = es.private_bytes_raw()
        es_pk_bytes = es.public_key().public_bytes_raw()

        params = {
            "state": request.state or None,
            "code_verifier": request.code_verifier or None,
            "autogenerate_code_verifier": request.autogenerate_code_verifier,
            "redirect_url": request.redirect_url or None,
            "request_identifier": request.request_identifier or None,
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
                pipe["error"],
                grpc.StatusCode.INVALID_ARGUMENT,
                error_type="UNKNOWN",
            )

        result = pipe["result"]

        encrypted_url = rrs.v1_oauth_encrypt(
            ec_pk=ec_pk_bytes,
            ss_kid=ss.private_bytes_raw(),
            es=es_bytes,
            url=result["authorization_url"].encode(),
        )

        context.set_trailing_metadata(
            [
                ("x-key-id", str(ss_kid)),
                ("x-public-key", base64.urlsafe_b64encode(es_pk_bytes).decode()),
            ]
        )

        return response(
            ciphertext=encrypted_url,
            state=result.get("state"),
            code_verifier=result.get("code_verifier"),
            client_id=result.get("client_id"),
            scope=result.get("scope"),
            redirect_url=result.get("redirect_url"),
            message="Successfully generated and encrypted authorization URL",
        )

    except NotImplementedError as exc:
        return self.handle_create_grpc_error_response(
            context,
            response,
            exc,
            grpc.StatusCode.UNIMPLEMENTED,
        )

    except LookupError as exc:
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
