# SPDX-License-Identifier: GPL-3.0-only


from fastapi import APIRouter, Depends, HTTPException, Path
from sqlalchemy.orm import Session

from publisher.api.rest.v1.errors import error_responses
from publisher.api.rest.v1.schemas import ServerStaticPublicKey
from publisher.db import get_db
from publisher.models.server_identity_key import get_public_key, get_public_keys

router = APIRouter(prefix="/server-keys", tags=["Server Keys"])


@router.get("", response_model=list[ServerStaticPublicKey], summary="List server keys")
def list_server_static_keys(db: Session = Depends(get_db)):
    """Static keys for gRPC v3 encryption."""
    return get_public_keys(db)


@router.get(
    "/{key_id}",
    response_model=ServerStaticPublicKey,
    summary="Get server key",
    responses=error_responses({404: "No key with that ID."}),
)
def get_server_static_key(
    key_id: int = Path(..., ge=0, le=255, description="Static key identifier, 0-255"),
    db: Session = Depends(get_db),
):
    try:
        return get_public_key(db, key_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
