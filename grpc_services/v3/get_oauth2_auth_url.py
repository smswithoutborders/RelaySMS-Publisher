# SPDX-License-Identifier: GPL-3.0-only
"""GetOAuth2AuthorizationUrl handler."""

from grpc_services.utils import call_adapter, require_fields
from protos.v3 import publisher_pb2
from publisher.platforms.manager import AdapterManager


def get_oauth2_authorization_url(
    request, adapter_manager: AdapterManager
) -> publisher_pb2.GetOAuth2AuthorizationUrlResponse:
    require_fields(request, "platform")

    adapter = adapter_manager.get_oauth2_adapter(request.platform)
    result = call_adapter(
        adapter,
        "get_authorization_url",
        {
            "state": request.state or None,
            "code_verifier": request.code_verifier or None,
            "autogenerate_code_verifier": request.autogenerate_code_verifier,
            "redirect_url": request.redirect_url or None,
            "request_identifier": request.request_identifier or None,
            "base_path": adapter.assets_path,
        },
    )

    return publisher_pb2.GetOAuth2AuthorizationUrlResponse(
        authorization_url=result["authorization_url"],
        state=result.get("state"),
        code_verifier=result.get("code_verifier"),
        client_id=result.get("client_id"),
        scope=result.get("scope"),
        redirect_url=result.get("redirect_url"),
        message="Successfully generated authorization URL",
    )
