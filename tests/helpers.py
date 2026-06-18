# SPDX-License-Identifier: GPL-3.0-only
"""Shared helpers for gRPC test CLI."""

import base64
import json
import secrets
from contextlib import contextmanager
from pathlib import Path

import grpc
import requests
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey

from lib_relaysms_payload_specs.generated import relaysms_spec_payload as rrs
from utils import get_logger

logger = get_logger(__name__)

DB_PATH = Path("tests/db.json")


# ---------------------------------------------------------------------------
# DB
# ---------------------------------------------------------------------------


def db_read() -> dict:
    return json.loads(DB_PATH.read_text()) if DB_PATH.exists() else {}


def db_write(data: dict) -> None:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    DB_PATH.write_text(json.dumps(data, indent=2))


def db_get(key: str):
    return db_read().get(key)


def db_set(key: str, value) -> None:
    data = db_read()
    data[key] = value
    db_write(data)


# ---------------------------------------------------------------------------
# Encoding
# ---------------------------------------------------------------------------


def b64(data: bytes, *, urlsafe: bool = True, truncate: int = 0) -> str:
    encoded = (
        base64.urlsafe_b64encode(data).decode()
        if urlsafe
        else base64.b64encode(data).decode()
    )
    return encoded[:truncate] + "..." if truncate else encoded


def b64d(data: str) -> bytes:
    return base64.urlsafe_b64decode(data)


# ---------------------------------------------------------------------------
# gRPC
# ---------------------------------------------------------------------------


@contextmanager
def grpc_channel(host: str, port: int, use_tls: bool):
    channel = (
        grpc.secure_channel(f"{host}:{port}", grpc.ssl_channel_credentials())
        if use_tls
        else grpc.insecure_channel(f"{host}:{port}")
    )
    try:
        yield channel
    finally:
        channel.close()


def grpc_call(fn, *args, **kwargs) -> tuple:
    try:
        return fn(*args, **kwargs), None
    except grpc.RpcError as e:
        return None, f"gRPC error: {e.code()} -- {e.details()}"


# ---------------------------------------------------------------------------
# Server identity keys
# ---------------------------------------------------------------------------


def fetch_server_identity_public_key(rest_api_url: str, key_id: int) -> bytes:
    url = f"{rest_api_url}/v1/server-keys/{key_id}"
    resp = requests.get(url)
    resp.raise_for_status()
    pk_b64 = resp.json().get("public_key")
    if not pk_b64:
        raise ValueError(f"No 'public_key' in response from {url}")
    return base64.urlsafe_b64decode(pk_b64)


def build_v1_request_metadata(
    rest_api: str, method_name: str, payload: bytes | None = None
) -> tuple[bytes, bytes, list[tuple]]:
    """Fetch a random server identity key, encrypt the request, return metadata headers."""
    key_id = secrets.randbelow(256)
    ss_pk_bytes = fetch_server_identity_public_key(rest_api, key_id)

    ec = X25519PrivateKey.generate()
    ec_bytes = ec.private_bytes_raw()
    ec_pk_bytes = ec.public_key().public_bytes_raw()

    encrypted = rrs.v1_requests_encrypt(
        ec=ec_bytes,
        ss_kid_pk=ss_pk_bytes,
        method_name=method_name.encode(),
        payload=payload,
    )

    return (
        ec_bytes,
        ec_pk_bytes,
        [
            ("x-payload-bin", encrypted.ciphertext),
            ("x-public-key-bin", ec_pk_bytes),
            ("x-key-id", str(key_id)),
            ("x-nonce-bin", encrypted.nonce),
            ("x-timestamp", str(encrypted.timestamp)),
        ],
    )


def fetch_platform_info(rest_api_url: str, platform: str) -> dict | None:
    url = f"{rest_api_url}/v1/platforms/{platform}"
    resp = requests.get(url)
    resp.raise_for_status()
    return resp.json()


# ---------------------------------------------------------------------------
# Interactive
# ---------------------------------------------------------------------------


def select_token_interactively(tokens: dict) -> str | None:
    if not tokens:
        return None
    identifiers = list(tokens.keys())
    if len(identifiers) == 1:
        return identifiers[0]

    print("\nAvailable tokens:")
    for i, ident in enumerate(identifiers, 1):
        platform = tokens[ident].get("platform", "unknown")
        print(f"  {i}. {ident} ({platform})")

    while True:
        choice = (
            input(f"\nSelect token (1-{len(identifiers)}) [q to quit]: ")
            .strip()
            .lower()
        )
        if choice == "q":
            return None
        try:
            idx = int(choice) - 1
            if 0 <= idx < len(identifiers):
                return identifiers[idx]
        except (ValueError, IndexError):
            pass
        print(f"Enter 1-{len(identifiers)} or 'q'.")
