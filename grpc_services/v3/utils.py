# SPDX-License-Identifier: GPL-3.0-only
"""Shared utilities for V3 gRPC service handlers."""

import threading
import time

import grpc
from cachetools import TTLCache

from lib_relaysms_payload_specs.generated import relaysms_spec_payload as rrs
from logutils import get_logger
from models.server_identity_key import get_private_key
from platforms.adapter_manager import AdapterManager

logger = get_logger(__name__)


def get_oauth2_adapter(platform: str) -> dict:
    """Resolve the OAuth2 adapter for a platform, raising NotImplementedError if unsupported."""
    adapter = AdapterManager.get_adapter_path(name=platform.lower(), protocol="oauth2")
    if not adapter:
        raise NotImplementedError(
            f"Platform '{platform.lower()}' with protocol 'oauth2' is not supported. "
            "Contact the developers for implementation status."
        )
    return adapter


def _resolve_ss_kid(key_id_raw: str) -> tuple[bytes | None, str | None]:
    try:
        key_id = int(key_id_raw)
    except (ValueError, TypeError):
        logger.warning(
            "Request rejected -- X-Key-ID is not a valid integer: %r", key_id_raw
        )
        return None, "x-key-id is not a valid integer"

    try:
        private_key = get_private_key(key_id)
        ss_kid = private_key.private_bytes_raw()
        return ss_kid, None
    except ValueError as e:
        logger.warning(
            "Request rejected -- key lookup failed for key_id=%s: %s", key_id, e
        )
        return None, str(e)
    except Exception as e:
        logger.error(
            "Unexpected error fetching private key for key_id=%s: %s", key_id, e
        )
        return None, "failed to retrieve server identity key"


def verify_v1_request(
    context: grpc.ServicerContext,
    nonce_cache: TTLCache,
    nonce_lock: threading.Lock,
    nonce_cache_ttl: int,
) -> tuple[rrs.ResponsePayload | None, str | None]:
    """
    Extract headers from gRPC context, verify timestamp and nonce,
    resolve the server static key by key ID, and decrypt the request
    payload using v1_requests_decrypt.
    """
    metadata = dict(context.invocation_metadata())

    ciphertext = metadata.get("x-payload-bin")
    ec_pk = metadata.get("x-public-key-bin")
    key_id_raw = metadata.get("x-key-id")
    nonce = metadata.get("x-nonce-bin")
    timestamp_raw = metadata.get("x-timestamp")

    missing = [
        name
        for name, val in [
            ("x-payload-bin", ciphertext),
            ("x-public-key-bin", ec_pk),
            ("x-key-id", key_id_raw),
            ("x-nonce-bin", nonce),
            ("x-timestamp", timestamp_raw),
        ]
        if not val
    ]
    if missing:
        reason = f"missing required headers: {', '.join(missing)}"
        logger.warning("Request rejected -- %s", reason)
        return None, reason

    try:
        timestamp = int(timestamp_raw)
    except ValueError:
        logger.warning(
            "Request rejected -- x-timestamp is not a valid integer: %r", timestamp_raw
        )
        return None, "x-timestamp is not a valid integer"

    timestamp_diff = abs(int(time.time()) - timestamp)
    if timestamp_diff > nonce_cache_ttl:
        logger.warning(
            "Request rejected -- outdated timestamp (diff=%ds, window=%ds)",
            timestamp_diff,
            nonce_cache_ttl,
        )
        return None, "outdated timestamp detected in request"

    with nonce_lock:
        if nonce in nonce_cache:
            logger.warning("Request rejected -- replayed nonce detected")
            return None, "nonce has already been used"
        nonce_cache[nonce] = True

    ss_kid, key_error = _resolve_ss_kid(key_id_raw)
    if key_error:
        return None, key_error

    try:
        request_payload = rrs.v1_requests_decrypt(
            ss_kid=ss_kid, ec_pk=ec_pk, nonce=nonce, ciphertext=ciphertext
        )
        return request_payload, None
    except rrs.V1CryptographicError.FailedToDecrypt as e:
        logger.warning("v1_requests_decrypt failed: %s", e)
        return None, "decryption failed"
