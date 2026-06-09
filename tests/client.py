#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""CLI tool for testing gRPC flows."""

import argparse
import base64
import json
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


def grpc_call(fn, *args, **kwargs) -> tuple:
    """Wrap a gRPC call, returning (result, None) or (None, error_message)."""
    try:
        return fn(*args, **kwargs), None
    except grpc.RpcError as e:
        return None, f"gRPC error: {e.code()} -- {e.details()}"


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------


def cmd_get_oauth2_url(args: argparse.Namespace) -> bool:
    """Test GetOAuth2AuthorizationUrl."""
    ec = X25519PrivateKey.generate()
    ec_pk_bytes = ec.public_key().public_bytes_raw()
    ec_bytes = ec.private_bytes_raw()

    logger.info(
        "Platform: %s | gRPC: %s:%d | TLS: %s",
        args.platform,
        args.host,
        args.port,
        args.tls,
    )
    logger.info("Client ephemeral public key: %s", b64(ec_pk_bytes, truncate=40))

    with grpc_channel(args.host, args.port, args.tls) as channel:
        stub = publisher_pb2_grpc.PublisherStub(channel)
        request = publisher_pb2.GetOAuth2AuthorizationUrlRequest(
            platform=args.platform,
            state=args.state or "",
            autogenerate_code_verifier=not args.no_auto_verifier,
        )

        result, err = grpc_call(
            stub.GetOAuth2AuthorizationUrl.with_call,
            request,
            metadata=[("x-public-key", b64(ec_pk_bytes))],
        )
        if err:
            logger.error(err)
            return False

        response, call = result
        trailing = dict(call.trailing_metadata())
        ss_kid = int(trailing.get("x-key-id", "-1"))
        es_pk_bytes = base64.urlsafe_b64decode(trailing.get("x-public-key", ""))

        try:
            logger.info("Fetching server identity public key (kid=%d) ...", ss_kid)
            ss_pk_bytes = fetch_server_identity_public_key(args.rest_api, ss_kid)
            logger.info(
                "Server identity public key (kid=%d): %s",
                ss_kid,
                b64(ss_pk_bytes, truncate=40),
            )
            logger.info("Running DH handshake + decryption ...")

            authorization_url = rrs.v1_oauth_decrypt(
                ec_kid=ec_bytes,
                ss_kid_pk=ss_pk_bytes,
                es_kid_pk=es_pk_bytes,
                ciphertext=response.ciphertext,
            ).decode()
        except Exception as e:
            logger.exception("Decryption failed: %s", e)
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

    print(f"Authorization URL : {authorization_url}")
    print(f"State             : {response.state}")
    print(f"Code Verifier     : {response.code_verifier}")
    print(f"Client ID         : {response.client_id}")
    print(f"Scope             : {response.scope}")
    print(f"Redirect URL      : {response.redirect_url}")
    return True


def cmd_exchange_oauth2_code(args: argparse.Namespace) -> bool:
    """Test ExchangeOAuth2CodeAndStore."""
    logger.info("Platform: %s | Code: %s...", args.platform, args.code[:12])

    # fall back to stored code_verifier if not provided
    code_verifier = args.code_verifier
    if not code_verifier:
        stored = db_get("oauth2") or {}
        code_verifier = stored.get("code_verifier", "")
        if code_verifier:
            logger.info("Using stored code_verifier from %s", DB_PATH)

    with grpc_channel(args.host, args.port, args.tls) as channel:
        stub = publisher_pb2_grpc.PublisherStub(channel)
        request = publisher_pb2.ExchangeOAuth2CodeAndStoreRequest(
            platform=args.platform,
            authorization_code=args.code,
            code_verifier=code_verifier,
            redirect_url=args.redirect_url or "",
        )

        response, err = grpc_call(stub.ExchangeOAuth2CodeAndStore, request)
        if err:
            logger.error(err)
            return False

    token_hash_b64 = b64(response.token_hash)
    db_set(
        "token",
        {
            "platform": args.platform,
            "account_identifier": response.account_identifier,
            "token_hash": token_hash_b64,
            "server_ephemeral_public_keys": [
                {"key_id": k.key_id, "public_key": b64(k.public_key)}
                for k in response.server_ephemeral_public_key
            ],
        },
    )
    logger.info("Saved token data to %s", DB_PATH)

    print(f"Success            : {response.success}")
    print(f"Message            : {response.message}")
    print(f"Account Identifier : {response.account_identifier}")
    print(f"Token Hash         : {token_hash_b64}")
    for key in response.server_ephemeral_public_key:
        print(f"Server Key [{key.key_id:>3}]  : {b64(key.public_key, truncate=40)}")
    return True


def cmd_upload_client_keys(args: argparse.Namespace) -> bool:
    """Test UploadClientEphemeralPublicKeys."""
    token_hash_b64 = args.token_hash
    if not token_hash_b64:
        stored = db_get("token") or {}
        token_hash_b64 = stored.get("token_hash")
        if not token_hash_b64:
            logger.error("No token_hash provided and none found in %s", DB_PATH)
            return False
        logger.info("Using stored token_hash from %s", DB_PATH)

    token_hash = base64.urlsafe_b64decode(token_hash_b64)

    keys = [X25519PrivateKey.generate() for _ in range(256)]
    client_public_keys = [
        publisher_pb2.PublicKey(key_id=i, public_key=k.public_key().public_bytes_raw())
        for i, k in enumerate(keys)
    ]

    logger.info("Uploading 256 client ephemeral public keys ...")

    with grpc_channel(args.host, args.port, args.tls) as channel:
        stub = publisher_pb2_grpc.PublisherStub(channel)
        request = publisher_pb2.UploadClientEphemeralPublicKeysRequest(
            token_hash=token_hash,
            client_ephemeral_public_key=client_public_keys,
        )

        response, err = grpc_call(stub.UploadClientEphemeralPublicKeys, request)
        if err:
            logger.error(err)
            return False

    token_id_b64 = b64(response.token_id)
    db_set(
        "client_keys",
        {
            "token_hash": token_hash_b64,
            "token_id": token_id_b64,
            "private_keys": [b64(k.private_bytes_raw()) for k in keys],
        },
    )
    logger.info("Saved client key private bytes to %s", DB_PATH)

    print(f"Success   : {response.success}")
    print(f"Message   : {response.message}")
    print(f"Token ID  : {token_id_b64}")
    return True


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

COMMANDS = {
    "get-oauth2-url": cmd_get_oauth2_url,
    "exchange-oauth2-code": cmd_exchange_oauth2_code,
    "upload-client-keys": cmd_upload_client_keys,
}


def build_parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(
        description="CLI test tool for gRPC flows.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python -m tests.client get-oauth2-url --platform gmail
  python -m tests.client exchange-oauth2-code --platform gmail --code AUTH_CODE
  python -m tests.client upload-client-keys
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
        help="Fetch and decrypt an OAuth2 authorization URL",
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

    p_upload = sub.add_parser(
        "upload-client-keys",
        parents=[shared],
        help="Upload 256 client ephemeral public keys",
    )
    p_upload.add_argument(
        "--token-hash",
        metavar="HASH",
        help="Token hash base64url (falls back to db.json)",
    )

    return root


def main():
    parser = build_parser()
    args = parser.parse_args()
    sys.exit(0 if COMMANDS[args.command](args) else 1)


if __name__ == "__main__":
    main()
