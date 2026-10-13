# SPDX-License-Identifier: GPL-3.0-only
"""GetOAuth2AuthorizationUrl handler."""

import secrets

from protos.v3 import publisher_pb2
from publisher.api.grpc.utils import call_adapter, find_adapter, require_fields
from publisher.models.platform_adapter import OAUTH2
from relaysms_adapter_sdk import AuthorizationRequest


def get_oauth2_authorization_url(
    request,
) -> publisher_pb2.GetOAuth2AuthorizationUrlResponse:
    require_fields(request, "platform")

    adapter = find_adapter(request.platform, OAUTH2)
    code_verifier = request.code_verifier or None
    if request.autogenerate_code_verifier and not code_verifier:
        code_verifier = secrets.token_urlsafe(48)
    result = call_adapter(
        adapter,
        "create_authorization_url",
        AuthorizationRequest(
            state=request.state or None,
            code_verifier=code_verifier,
            redirect_url=request.redirect_url or None,
            request_identifier=request.request_identifier or None,
        ),
    )

    return publisher_pb2.GetOAuth2AuthorizationUrlResponse(
        authorization_url=result["url"],
        state=result.get("state"),
        code_verifier=result.get("code_verifier"),
        client_id=result.get("client_id"),
        scope=result.get("scope"),
        redirect_url=result.get("redirect_url"),
        message="Successfully generated authorization URL",
    )
