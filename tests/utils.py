# SPDX-License-Identifier: GPL-3.0-only
"""Shared helpers for gRPC test CLI."""

import base64
import json
import secrets
import sys
from contextlib import contextmanager
from pathlib import Path

import grpc
import requests
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey

from lib_relaysms_payload_specs.generated import relaysms_spec_payload as rrs
from utils import get_logger

logger = get_logger(__name__)

DB_PATH = Path("tests/db.json")


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


def b64(data: bytes, *, urlsafe: bool = True, truncate: int = 0) -> str:
    encoded = (
        base64.urlsafe_b64encode(data).decode()
        if urlsafe
        else base64.b64encode(data).decode()
    )
    return encoded[:truncate] + "..." if truncate else encoded


def b64d(data: str) -> bytes:
    return base64.urlsafe_b64decode(data)


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
        timestamp=None,
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


def fetch_platform_info(rest_api_url: str, platform: str) -> dict:
    url = f"{rest_api_url}/v1/platforms?name={platform}"
    resp = requests.get(url)
    resp.raise_for_status()
    return resp.json()[0]


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


def read_attachment(attachment):
    if not attachment:
        return None
    try:
        with open(attachment, "rb") as f:
            data = f.read()
        logger.info("attachment loaded: %d bytes from %s", len(data), attachment)
        return data
    except Exception as e:
        logger.error("failed to read attachment: %s", e)
        sys.exit(1)


def prepare_platform_send(
    rest_api, platform, to, subject, body, attachment_bytes, token
):
    p_lower = platform.lower()
    tokens = db_get("tokens") or {}
    if not tokens:
        logger.error("no tokens found")
        sys.exit(1)

    platform_tokens = {
        ident: d
        for ident, d in tokens.items()
        if d.get("platform", "").lower() == p_lower
    }
    if not platform_tokens:
        logger.error("no tokens found for platform %r.", platform)
        sys.exit(1)

    if token:
        account_id = next(
            (ident for ident, d in platform_tokens.items() if d.get("token") == token),
            None,
        )
        if not account_id:
            logger.error("token not found for platform %r", platform)
            sys.exit(1)
    else:
        account_id = select_token_interactively(platform_tokens)

    if not account_id:
        sys.exit(1)

    token_data = tokens[account_id]
    remaining_keypairs = token_data.get("client_ephemeral_keypairs", [])
    if not remaining_keypairs:
        logger.error("no client keypairs remaining for %s.", account_id)
        sys.exit(1)

    has_attachment = attachment_bytes is not None
    eligible_keypairs = (
        [k for k in remaining_keypairs if k["key_id"] <= 15]
        if has_attachment
        else remaining_keypairs
    )
    if not eligible_keypairs:
        logger.error(
            "no eligible keypairs (key_id <= 15) remaining for %s.", account_id
        )
        sys.exit(1)

    kp = secrets.choice(eligible_keypairs)
    kid_index = kp["key_id"]

    es_entry = next(
        (
            k
            for k in token_data["server_ephemeral_public_keys"]
            if k["key_id"] == kid_index
        ),
        None,
    )
    if not es_entry:
        logger.error("es_kid_pk not found for kid_index=%d", kid_index)
        sys.exit(1)

    try:
        ss_kid_pk = fetch_server_identity_public_key(rest_api, kid_index)
    except Exception as e:
        logger.error("failed to fetch ss_kid_pk for kid_index=%d: %s", kid_index, e)
        sys.exit(1)

    try:
        platform_info = fetch_platform_info(rest_api, p_lower)
    except Exception as e:
        logger.error("failed to fetch platform info for %r: %s", platform, e)
        sys.exit(1)

    logger.info(
        "platform=%s | cat_id=%s | key_id=%d",
        platform_info["name"],
        platform_info["cat_id"],
        kid_index,
    )

    try:
        cat_id = rrs.v1_content_category_from_u8(platform_info["cat_id"])
        content_bytes = rrs.V1ContentsContainer(
            cat_id=cat_id,
            body=body.encode(),
            to=to.encode() if to else None,
            subject=subject.encode() if subject else None,
            attachment=attachment_bytes,
        ).serialize()
    except Exception as e:
        logger.exception("V1ContentsContainer.serialize failed: %s", e)
        sys.exit(1)

    try:
        encrypted_content = rrs.v1_platform_publisher_encrypt(
            ec_kid=b64d(kp["private_key"]),
            ss_kid_pk=ss_kid_pk,
            es_kid_pk=b64d(es_entry["public_key"]),
            key_id=kid_index,
            plaintext=content_bytes,
        )
    except Exception as e:
        logger.exception("v1_platform_publisher_encrypt failed: %s", e)
        sys.exit(1)

    def cleanup():
        token_data["client_ephemeral_keypairs"] = [
            k
            for k in token_data["client_ephemeral_keypairs"]
            if k["key_id"] != kid_index
        ]
        token_data["server_ephemeral_public_keys"] = [
            k
            for k in token_data["server_ephemeral_public_keys"]
            if k["key_id"] != kid_index
        ]
        db_set("tokens", tokens)

    label = f"platform={p_lower} | account={account_id}"
    return encrypted_content, kid_index, token_data["token_id"], label, cleanup


def prepare_offline_send(rest_api, to, subject, body, attachment_bytes):
    has_attachment = attachment_bytes is not None
    ss_kid = secrets.randbelow(16 if has_attachment else 256)
    try:
        ss_pk = fetch_server_identity_public_key(rest_api, ss_kid)
    except Exception as e:
        logger.error("failed to fetch ss_kid_pk for kid_index=%d: %s", ss_kid, e)
        sys.exit(1)

    ec_keypair = X25519PrivateKey.generate()
    sc_keypair = X25519PrivateKey.generate()

    try:
        cat_id = rrs.V1ContentCategories.EMAIL
        content_bytes = rrs.V1ContentsContainer(
            cat_id=cat_id,
            body=body.encode(),
            to=to.encode(),
            subject=subject.encode() if subject else None,
            attachment=attachment_bytes,
        ).serialize()
    except Exception as e:
        logger.exception("V1ContentsContainer.serialize failed: %s", e)
        sys.exit(1)

    try:
        offline_first = rrs.OfflineFirst.encrypt(
            ss_pk=ss_pk,
            ec=ec_keypair.private_bytes_raw(),
            sc=sc_keypair.private_bytes_raw(),
            payload=content_bytes,
        )
        encrypted_content = offline_first.serialize()
    except Exception:
        logger.exception("OfflineFirst.encrypt failed:")
        sys.exit(1)

    def cleanup():
        pass

    label = "offline"
    return encrypted_content, ss_kid, None, label, cleanup
