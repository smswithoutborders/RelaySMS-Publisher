#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""CLI tool for testing gRPC flows."""

import argparse
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
from protos.v3 import publisher_pb2, publisher_pb2_grpc
from utils import get_logger

logger = get_logger("test_cli")

DB_PATH = Path("tests/db.json")


# ---------------------------------------------------------------------------
# Local test DB
# ---------------------------------------------------------------------------


def db_read() -> dict:
    """Read the local test DB."""
    if not DB_PATH.exists():
        return {}
    return json.loads(DB_PATH.read_text())


def db_write(data: dict) -> None:
    """Write to the local test DB."""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    DB_PATH.write_text(json.dumps(data, indent=2))


def db_get(key: str):
    """Get a value from the local test DB."""
    return db_read().get(key)


def db_set(key: str, value) -> None:
    """Set a value in the local test DB."""
    data = db_read()
    data[key] = value
    db_write(data)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


@contextmanager
def grpc_channel(host: str, port: int, use_tls: bool):
    """Yield an open gRPC channel, closing it on exit."""
    channel = (
        grpc.secure_channel(f"{host}:{port}", grpc.ssl_channel_credentials())
        if use_tls
        else grpc.insecure_channel(f"{host}:{port}")
    )
    try:
        yield channel
    finally:
        channel.close()


def fetch_server_identity_public_key(rest_api_url: str, key_id: int) -> bytes:
    """Fetch a server identity public key from the REST API."""
    url = f"{rest_api_url}/v1/server-keys/{key_id}"
    response = requests.get(url)
    response.raise_for_status()
    public_key_b64 = response.json().get("public_key")
    if not public_key_b64:
        raise ValueError(f"No 'public_key' in response from {url}")
    return base64.urlsafe_b64decode(public_key_b64)


def b64(data: bytes, *, truncate: int = 0) -> str:
    """URL-safe base64-encode bytes, optionally truncated for display."""
    encoded = base64.urlsafe_b64encode(data).decode()
    return encoded[:truncate] + "..." if truncate else encoded


def b64_decode(data: str) -> bytes:
    """Decode a URL-safe base64 string."""
    return base64.urlsafe_b64decode(data)


def grpc_call(fn, *args, **kwargs) -> tuple:
    """Wrap a gRPC call, returning (result, None) or (None, error_message)."""
    try:
        return fn(*args, **kwargs), None
    except grpc.RpcError as e:
        return None, f"gRPC error: {e.code()} -- {e.details()}"


def build_v1_request_metadata(
    ss_pk_bytes: bytes, key_id: int, method_name: str, payload: bytes | None = None
) -> tuple[bytes, bytes, list[tuple]]:
    """
    Generate a client ephemeral keypair, encrypt the request payload
    using v1_requests_encrypt, and return the gRPC metadata headers.

    Returns:
        (ec_bytes, ec_pk_bytes, metadata_list)
    """
    ec = X25519PrivateKey.generate()
    ec_pk_bytes = ec.public_key().public_bytes_raw()
    ec_bytes = ec.private_bytes_raw()

    encrypted = rrs.v1_requests_encrypt(
        ec=ec_bytes,
        ss_kid_pk=ss_pk_bytes,
        method_name=method_name.encode(),
        payload=payload,
    )

    metadata = [
        ("x-payload-bin", encrypted.ciphertext),
        ("x-public-key-bin", ec_pk_bytes),
        ("x-key-id", str(key_id)),
        ("x-nonce-bin", encrypted.nonce),
        ("x-timestamp", str(encrypted.timestamp)),
    ]
    return ec_bytes, ec_pk_bytes, metadata


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------


def cmd_get_oauth2_url(args: argparse.Namespace) -> bool:
    """Test GetOAuth2AuthorizationUrl."""
    logger.info(
        "Platform: %s | gRPC: %s:%d | TLS: %s",
        args.platform,
        args.host,
        args.port,
        args.tls,
    )

    try:
        key_id = secrets.randbelow(256)
        logger.info("Fetching server identity public key (kid=%d) ...", key_id)
        ss_pk_bytes = fetch_server_identity_public_key(args.rest_api, key_id)
        logger.info(
            "Server identity public key (kid=%d): %s",
            key_id,
            b64(ss_pk_bytes, truncate=40),
        )
    except Exception as e:
        logger.error("Failed to fetch server identity public key: %s", e)
        return False

    try:
        _, ec_pk_bytes, metadata = build_v1_request_metadata(
            ss_pk_bytes=ss_pk_bytes,
            key_id=key_id,
            method_name="/publisher.v3.Publisher/GetOAuth2AuthorizationUrl",
        )
        logger.info("Client ephemeral public key: %s", b64(ec_pk_bytes, truncate=40))
    except Exception as e:
        logger.error("Failed to build request metadata: %s", e)
        return False

    with grpc_channel(args.host, args.port, args.tls) as channel:
        stub = publisher_pb2_grpc.PublisherStub(channel)
        request = publisher_pb2.GetOAuth2AuthorizationUrlRequest(
            platform=args.platform,
            state=args.state or "",
            autogenerate_code_verifier=not args.no_auto_verifier,
        )

        response, err = grpc_call(
            stub.GetOAuth2AuthorizationUrl, request, metadata=metadata
        )
        if err:
            logger.error(err)
            return False

    db_set(
        "oauth2",
        {
            "platform": args.platform,
            "state": response.state,
            "code_verifier": response.code_verifier,
            "client_id": response.client_id,
            "scope": response.scope,
            "redirect_url": response.redirect_url,
        },
    )
    logger.info("Saved OAuth2 session data to %s", DB_PATH)

    print(f"Authorization URL : {response.authorization_url}")
    print(f"State             : {response.state}")
    print(f"Code Verifier     : {response.code_verifier}")
    print(f"Client ID         : {response.client_id}")
    print(f"Scope             : {response.scope}")
    print(f"Redirect URL      : {response.redirect_url}")
    return True


def cmd_exchange_oauth2_code(args: argparse.Namespace) -> bool:
    """Test ExchangeOAuth2CodeAndStore.

    Generates 256 client ephemeral keypairs, sends them with the exchange
    request, receives the encrypted token, and decrypts it using
    v1_token_decrypt_client with the kid_index from the response.
    """
    logger.info("Platform: %s | Code: %s...", args.platform, args.code[:12])

    code_verifier = args.code_verifier
    if not code_verifier:
        stored = db_get("oauth2") or {}
        code_verifier = stored.get("code_verifier", "")
        if code_verifier:
            logger.info("Using stored code_verifier from %s", DB_PATH)

    try:
        key_id = secrets.randbelow(256)
        logger.info("Fetching server identity public key (kid=%d) ...", key_id)
        ss_pk_bytes = fetch_server_identity_public_key(args.rest_api, key_id)
        logger.info(
            "Server identity public key (kid=%d): %s",
            key_id,
            b64(ss_pk_bytes, truncate=40),
        )
    except Exception as e:
        logger.error("Failed to fetch server identity public key: %s", e)
        return False

    logger.info("Generating 256 client ephemeral keypairs ...")
    client_keypairs = [X25519PrivateKey.generate() for _ in range(256)]
    client_public_keys = [
        publisher_pb2.PublicKey(
            key_id=i,
            public_key=kp.public_key().public_bytes_raw(),
        )
        for i, kp in enumerate(client_keypairs)
    ]

    try:
        _, _, metadata = build_v1_request_metadata(
            ss_pk_bytes=ss_pk_bytes,
            key_id=key_id,
            method_name="/publisher.v3.Publisher/ExchangeOAuth2CodeAndStore",
        )
    except Exception as e:
        logger.error("Failed to build request metadata: %s", e)
        return False

    with grpc_channel(args.host, args.port, args.tls) as channel:
        stub = publisher_pb2_grpc.PublisherStub(channel)
        request = publisher_pb2.ExchangeOAuth2CodeAndStoreRequest(
            platform=args.platform,
            authorization_code=args.code,
            code_verifier=code_verifier,
            redirect_url=args.redirect_url or "",
            client_ephemeral_public_keys=client_public_keys,
        )

        response, err = grpc_call(
            stub.ExchangeOAuth2CodeAndStore, request, metadata=metadata
        )
        if err:
            logger.error(err)
            return False

    if not response.success:
        logger.error("Exchange failed: %s", response.message)
        return False

    kid_index = response.key_id

    try:
        response_ss_kid_pk = fetch_server_identity_public_key(args.rest_api, kid_index)
    except Exception as e:
        logger.error("Failed to fetch server identity public key for decryption: %s", e)
        return False

    es_kid_pk_entry = next(
        (k for k in response.server_ephemeral_public_keys if k.key_id == kid_index),
        None,
    )
    if es_kid_pk_entry is None:
        logger.error(
            "Server ephemeral public key at kid_index=%d not found in response",
            kid_index,
        )
        return False

    es_kid_pk_bytes = es_kid_pk_entry.public_key
    ec_kid_private = client_keypairs[kid_index]

    try:
        raw_token = rrs.v1_token_decrypt_client(
            ec_kid=ec_kid_private.private_bytes_raw(),
            ss_kid_pk=response_ss_kid_pk,
            es_kid_pk=es_kid_pk_bytes,
            key_id=kid_index,
            received_payload=response.token_ciphertext,
        )
        logger.info("Token decrypted successfully using kid_index=%d", kid_index)
    except Exception as e:
        logger.error("Failed to decrypt token ciphertext: %s", e)
        return False

    token_id_b64 = b64(response.token_id)
    token_b64 = b64(raw_token)

    remaining_keypairs = [
        {
            "key_id": i,
            "public_key": b64(kp.public_key().public_bytes_raw()),
            "private_key": b64(kp.private_bytes_raw()),
        }
        for i, kp in enumerate(client_keypairs)
        if i != kid_index
    ]

    tokens = db_get("tokens") or {}
    tokens[token_b64] = {
        "platform": args.platform,
        "account_identifier": response.account_identifier,
        "key_id": kid_index,
        "token_id": token_id_b64,
        "server_identity_public_key": b64(response_ss_kid_pk),
        "server_ephemeral_public_keys": [
            {"key_id": k.key_id, "public_key": b64(k.public_key)}
            for k in response.server_ephemeral_public_keys
            if k.key_id != kid_index
        ],
        "client_ephemeral_keypairs": remaining_keypairs,
    }
    db_set("tokens", tokens)
    logger.info("Saved token data under token_id=%s to %s", token_id_b64, DB_PATH)

    print(f"Success            : {response.success}")
    print(f"Message            : {response.message}")
    print(f"Account Identifier : {response.account_identifier}")
    print(f"Token ID           : {token_id_b64}")
    print(f"Raw Token          : {b64(raw_token, truncate=40)}")
    print(f"Key ID / kid_index : {kid_index}")
    for key in response.server_ephemeral_public_keys:
        used = " (used)" if key.key_id == kid_index else ""
        print(
            f"Server Key [{key.key_id:>3}]  : {b64(key.public_key, truncate=40)}{used}"
        )
    return True


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

COMMANDS = {
    "get-oauth2-url": cmd_get_oauth2_url,
    "exchange-oauth2-code": cmd_exchange_oauth2_code,
}


def build_parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(
        description="CLI test tool for gRPC flows.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python -m tests.client get-oauth2-url --platform gmail
  python -m tests.client exchange-oauth2-code --platform gmail --code AUTH_CODE
        """,
    )

    shared = argparse.ArgumentParser(add_help=False)
    shared.add_argument(
        "--host", default="127.0.0.1", help="gRPC host (default: 127.0.0.1)"
    )
    shared.add_argument(
        "--port", type=int, default=6000, help="gRPC port (default: 6000)"
    )
    shared.add_argument(
        "--tls", action="store_true", help="Use TLS for gRPC connection"
    )
    shared.add_argument("--platform", "-p", help="Platform name (e.g. gmail)")
    shared.add_argument("--state", help="State parameter for CSRF protection")

    sub = root.add_subparsers(dest="command", metavar="COMMAND", required=True)

    p_get = sub.add_parser(
        "get-oauth2-url",
        parents=[shared],
        help="Encrypt a request and fetch an OAuth2 authorization URL",
    )
    p_get.add_argument(
        "--rest-api",
        default="http://localhost:16000",
        metavar="URL",
        help="REST API base URL for server key lookup",
    )
    p_get.add_argument(
        "--no-auto-verifier",
        action="store_true",
        help="Disable auto-generation of PKCE code verifier",
    )

    p_exchange = sub.add_parser(
        "exchange-oauth2-code",
        parents=[shared],
        help="Exchange an OAuth2 authorization code for tokens",
    )
    p_exchange.add_argument(
        "--rest-api",
        default="http://localhost:16000",
        metavar="URL",
        help="REST API base URL for server key lookup",
    )
    p_exchange.add_argument(
        "--code", required=True, help="Authorization code from the OAuth2 redirect"
    )
    p_exchange.add_argument(
        "--code-verifier",
        metavar="VERIFIER",
        help="PKCE code verifier (falls back to db.json)",
    )
    p_exchange.add_argument(
        "--redirect-url",
        metavar="URL",
        help="Redirect URL used in the original request",
    )

    return root


def main():
    parser = build_parser()
    args = parser.parse_args()
    sys.exit(0 if COMMANDS[args.command](args) else 1)


if __name__ == "__main__":
    main()
