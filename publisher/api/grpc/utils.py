# SPDX-License-Identifier: GPL-3.0-only
"""Shared helpers for gRPC service handlers."""

import logging

from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PublicKey
from grpc_interceptor.exceptions import Internal, InvalidArgument

from publisher.api.grpc.interceptors import INTERNAL_ERROR
from publisher.platforms import ipc
from publisher.platforms.manager import PlatformManifest

logger = logging.getLogger(__name__)


def require_fields(request, *fields: str) -> None:
    # Only for string, bytes and repeated fields: proto3 sends 0 and false as unset,
    # so a valid 0 id would be rejected.
    for field in fields:
        if not getattr(request, field, None):
            raise InvalidArgument(f"Missing required field: {field}")


def validate_client_ephemeral_public_keys(keys) -> None:
    if len(keys) != 256:
        raise InvalidArgument(
            "client_ephemeral_public_keys must contain exactly 256 keys, "
            f"got {len(keys)}"
        )
    if {k.key_id for k in keys} != set(range(256)):
        raise InvalidArgument(
            "client_ephemeral_public_keys must have each key_id 0-255 exactly once"
        )
    for key_obj in keys:
        if len(key_obj.public_key) != 32:
            raise InvalidArgument(
                f"Invalid key for key_id {key_obj.key_id}: "
                f"must be 32 bytes, got {len(key_obj.public_key)}"
            )
        try:
            X25519PublicKey.from_public_bytes(key_obj.public_key)
        except Exception as e:
            raise InvalidArgument(
                f"Invalid cryptographic key for key_id {key_obj.key_id}: {e}"
            ) from None


def call_adapter(adapter: PlatformManifest, method: str, params: dict) -> dict:
    pipe = ipc.invoke(
        adapter_path=adapter.path,
        venv_path=adapter.venv_path,
        method=method,
        params=params,
    )
    if pipe.get("error"):
        logger.error("Adapter error for platform %r: %s", adapter.name, pipe["error"])
        raise Internal(INTERNAL_ERROR)
    return pipe["result"]
