# SPDX-License-Identifier: GPL-3.0-only


from fastapi import APIRouter, Query, Request

from gateway_clients.gateway_client_manager import GatewayClientManager
from rest_services.v1.schemas import GatewayClientManifest

router = APIRouter(prefix="/gateway-clients", tags=["Gateway Clients"])

ALLOWED_GATEWAY_CLIENT_MANIFEST_KEYS = [
    "msisdn",
    "country",
    "operator",
    "operator_code",
    "protocols",
]


@router.get("", summary="List gateway clients")
def get_gateway_clients(
    request: Request,
    msisdn: str | None = Query(None, description="Filter by MSISDN"),
    country: str | None = Query(None, description="Filter by country"),
    operator: str | None = Query(None, description="Filter by operator"),
) -> list[GatewayClientManifest]:
    manager: GatewayClientManager = request.app.state.gateway_client_manager
    manifests = manager.list_clients(msisdn=msisdn, country=country, operator=operator)

    return [
        GatewayClientManifest(
            **{
                key: getattr(manifest, key)
                for key in ALLOWED_GATEWAY_CLIENT_MANIFEST_KEYS
            }
        )
        for manifest in manifests
    ]
