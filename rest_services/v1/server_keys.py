# SPDX-License-Identifier: GPL-3.0-only


from fastapi import APIRouter, HTTPException, Path

from publisher.models.server_identity_key import get_public_key, get_public_keys
from rest_services.v1.schemas import ServerStaticPublicKey

router = APIRouter(prefix="/server-keys", tags=["Server Keys"])


@router.get("", response_model=list[ServerStaticPublicKey], summary="List server keys")
def list_server_static_keys():
    return get_public_keys()


@router.get("/{key_id}", response_model=ServerStaticPublicKey, summary="Get server key")
def get_server_static_key(
    key_id: int = Path(..., ge=0, le=255, description="Static key identifier"),
):
    try:
        return get_public_key(key_id)
    except Exception as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
