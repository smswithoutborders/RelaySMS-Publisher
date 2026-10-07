# SPDX-License-Identifier: GPL-3.0-only


from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from publisher.api.rest.v1.schemas import GatewayClientManifest
from publisher.db import get_db
from publisher.models import gateway_client as gateway_clients

router = APIRouter(prefix="/gateway-clients", tags=["Gateway Clients"])


@router.get("", summary="List gateway clients")
def get_gateway_clients(
    msisdn: str | None = Query(None, max_length=20, description="Filter by MSISDN"),
    country: str | None = Query(None, max_length=100, description="Filter by country"),
    operator: str | None = Query(
        None, max_length=100, description="Filter by operator"
    ),
    db: Session = Depends(get_db),
) -> list[GatewayClientManifest]:
    """Numbers that relay SMS to this server. Country and operator ignore case."""
    return [
        GatewayClientManifest.model_validate(client)
        for client in gateway_clients.find(
            db, msisdn=msisdn, country=country, operator=operator
        )
    ]
