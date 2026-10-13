# SPDX-License-Identifier: GPL-3.0-only
"""Shared helpers for gRPC service handlers."""

import logging
from typing import Any

from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PublicKey
from grpc_interceptor.exceptions import Internal, InvalidArgument, ResourceExhausted

from publisher.api.grpc.interceptors import INTERNAL_ERROR
from publisher.db import get_session
from publisher.models import platform_adapter as platform_adapters
from publisher.models.platform_adapter import PlatformAdapter
from publisher.platforms import ipc
from relaysms_adapter_sdk import (
    AdapterError,
    AuthenticationError,
    InvalidParamsError,
    RateLimitedError,
)

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


def find_adapter(platform: str, proto_id: int) -> PlatformAdapter:
    # Its own session, so none stays open while the adapter runs.
    with get_session() as s:
        return platform_adapters.get_for_protocol(s, platform, proto_id)


def call_adapter(adapter: PlatformAdapter, method: str, request: Any) -> dict:
    """Call an adapter, turning its errors into gRPC errors.

    Rejected input and codes reach the client; anything else is logged.
    """
    try:
        return ipc.call(adapter, method, request)
    except (InvalidParamsError, AuthenticationError) as e:
        raise InvalidArgument(e.message) from None
    except RateLimitedError as e:
        raise ResourceExhausted(e.message) from None
    except AdapterError as e:
        logger.error("Adapter %r failed: %s", adapter.name, e.message)
        raise Internal(INTERNAL_ERROR) from None
