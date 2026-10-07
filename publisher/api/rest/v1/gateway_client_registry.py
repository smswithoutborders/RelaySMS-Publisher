# SPDX-License-Identifier: GPL-3.0-only
"""Managing gateway clients."""

import uuid
from contextlib import contextmanager

from fastapi import APIRouter, Depends, Query, Request, Response, Security
from sqlalchemy.orm import Session

from publisher.api.rest.v1.auth import AuthContext, authorize
from publisher.api.rest.v1.errors import (
    CONCURRENT_CHANGE,
    IF_MATCH_ERRORS,
    ApiError,
    error_responses,
)
from publisher.api.rest.v1.params import check_if_match, etag
from publisher.api.rest.v1.schemas import (
    GatewayClientCreate,
    GatewayClientInfo,
    GatewayClientSuggestion,
    GatewayClientUpdate,
)
from publisher.db import get_db
from publisher.gateway_clients import manager
from publisher.gateway_clients.manager import (
    GatewayClientConflictError,
    GatewayClientError,
    GatewayClientExistsError,
)
from publisher.models import credential as credentials
from publisher.models import gateway_client as gateway_clients
from publisher.models.credential import Scope
from publisher.models.gateway_client import GatewayClient

router = APIRouter(prefix="/gateway-clients", tags=["Gateway Client Registry"])

NOT_FOUND = {404: "No gateway client with that ID."}


def _etag(client: GatewayClient) -> str:
    return etag(client.id, client.version)


def _load(db: Session, client_id: uuid.UUID) -> GatewayClient:
    client = db.get(GatewayClient, client_id)
    if client is None:
        raise ApiError(404, "Gateway client not found.")
    return client


def _info(client: GatewayClient, names: dict) -> GatewayClientInfo:
    return GatewayClientInfo(
        id=client.id,
        msisdn=client.msisdn,
        country=client.country,
        operator=client.operator,
        operator_code=client.operator_code,
        protocols=client.protocols,
        enabled=client.is_enabled,
        created_at=client.created_at,
        created_by=names.get(client.created_by),
        updated_at=client.updated_at,
        updated_by=names.get(client.updated_by),
    )


def _respond(db: Session, response: Response, client: GatewayClient):
    response.headers["ETag"] = _etag(client)
    names = credentials.usernames(db, [client.created_by, client.updated_by])
    return _info(client, names)


@contextmanager
def _errors(context: AuthContext):
    by = f"actor {context.credential.id}"
    try:
        yield
    except (GatewayClientExistsError, GatewayClientConflictError) as e:
        raise ApiError(409, str(e), log=f"{by}: {e}") from None
    except GatewayClientError as e:
        raise ApiError(400, str(e), log=f"{by}: {e}") from None


@router.get(
    "/registry", response_model=list[GatewayClientInfo], summary="List all clients"
)
def list_clients(
    context: AuthContext = Security(authorize, scopes=[Scope.GC_READ]),
    db: Session = Depends(get_db),
) -> list[GatewayClientInfo]:
    """Every gateway client, disabled ones included. Scope: gc:read."""
    clients = gateway_clients.find(db, include_disabled=True)
    names = credentials.usernames(
        db, [i for c in clients for i in (c.created_by, c.updated_by)]
    )
    return [_info(client, names) for client in clients]


@router.post(
    "/registry",
    response_model=GatewayClientInfo,
    status_code=201,
    summary="Add client",
    responses=error_responses(
        {
            400: "An invalid MSISDN or operator code, or details that can't be "
            "resolved from the MSISDN.",
            409: "That MSISDN is already registered.",
        }
    ),
)
def create_client(
    body: GatewayClientCreate,
    request: Request,
    response: Response,
    context: AuthContext = Security(authorize, scopes=[Scope.GC_WRITE]),
    db: Session = Depends(get_db),
) -> GatewayClientInfo:
    """Country, operator and operator code are resolved if omitted. Scope: gc:write."""
    with _errors(context):
        client = manager.create(
            db,
            body.msisdn,
            body.protocols,
            country=body.country,
            operator=body.operator,
            operator_code=body.operator_code,
            actor=context.credential,
        )
    db.commit()
    response.headers["Location"] = str(
        request.url_for("get_client", client_id=client.id)
    )
    return _respond(db, response, client)


@router.get(
    "/registry/suggest",
    response_model=GatewayClientSuggestion,
    summary="Suggest client details",
    responses=error_responses({400: "The MSISDN isn't in E.164 format."}),
)
def suggest_client(
    msisdn: str = Query(..., max_length=20, description="Phone number in E.164"),
    context: AuthContext = Security(authorize, scopes=[Scope.GC_WRITE]),
) -> GatewayClientSuggestion:
    """Details and PLMN candidates to confirm before adding. Scope: gc:write."""
    with _errors(context):
        suggestion = manager.suggest(manager.check_msisdn(msisdn))
    return GatewayClientSuggestion.model_validate(suggestion)


@router.get(
    "/registry/{client_id}",
    response_model=GatewayClientInfo,
    summary="Get client",
    responses=error_responses(NOT_FOUND),
)
def get_client(
    client_id: uuid.UUID,
    response: Response,
    context: AuthContext = Security(authorize, scopes=[Scope.GC_READ]),
    db: Session = Depends(get_db),
) -> GatewayClientInfo:
    """Returns the ETag to send as If-Match. Scope: gc:read."""
    return _respond(db, response, _load(db, client_id))


@router.patch(
    "/registry/{client_id}",
    response_model=GatewayClientInfo,
    summary="Change client",
    responses=error_responses(
        NOT_FOUND,
        CONCURRENT_CHANGE,
        IF_MATCH_ERRORS,
        {400: "An invalid operator code."},
    ),
)
def update_client(
    client_id: uuid.UUID,
    body: GatewayClientUpdate,
    request: Request,
    response: Response,
    context: AuthContext = Security(authorize, scopes=[Scope.GC_WRITE]),
    db: Session = Depends(get_db),
) -> GatewayClientInfo:
    """Needs If-Match. Omitted fields stay as they are. Scope: gc:write."""
    client = _load(db, client_id)
    check_if_match(request, _etag(client), "gateway client")
    with _errors(context):
        manager.update(
            db,
            client,
            country=body.country,
            operator=body.operator,
            operator_code=body.operator_code,
            protocols=body.protocols,
            actor=context.credential,
        )
        if body.enabled is not None:
            manager.set_enabled(db, client, body.enabled, actor=context.credential)
    db.commit()
    return _respond(db, response, client)


@router.delete(
    "/registry/{client_id}",
    status_code=204,
    summary="Delete client",
    responses=error_responses(NOT_FOUND, CONCURRENT_CHANGE, IF_MATCH_ERRORS),
)
def delete_client(
    client_id: uuid.UUID,
    request: Request,
    context: AuthContext = Security(authorize, scopes=[Scope.GC_WRITE]),
    db: Session = Depends(get_db),
) -> Response:
    """Needs If-Match. To hide it for a while, disable it instead. Scope: gc:write."""
    client = _load(db, client_id)
    check_if_match(request, _etag(client), "gateway client")
    with _errors(context):
        manager.delete(db, client, actor=context.credential)
    db.commit()
    return Response(status_code=204)
