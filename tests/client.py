#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""CLI tool for testing gRPC flows."""

import argparse
import base64
import sys
from contextlib import contextmanager

import grpc
import requests
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey

from lib_relaysms_payload_specs.generated import relaysms_spec_payload as rrs
from protos.v3 import publisher_pb2, publisher_pb2_grpc
from utils import get_logger

logger = get_logger("test_cli")


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

    print(f"Authorization URL : {authorization_url}")
    print(f"State             : {response.state}")
    print(f"Code Verifier     : {response.code_verifier}")
    print(f"Client ID         : {response.client_id}")
    print(f"Scope             : {response.scope}")
    print(f"Redirect URL      : {response.redirect_url}")
    return True


def cmd_exchange_oauth2_code(args: argparse.Namespace) -> bool:
    """Test ExchangeOAuth2CodeAndStore."""
    logger.info("Platform: %s | Code: %s", args.platform, args.code[:12] + "...")

    with grpc_channel(args.host, args.port, args.tls) as channel:
        stub = publisher_pb2_grpc.PublisherStub(channel)
        request = publisher_pb2.ExchangeOAuth2CodeAndStoreRequest(
            platform=args.platform,
            authorization_code=args.code,
            code_verifier=args.code_verifier or "",
            redirect_url=args.redirect_url or "",
        )

        response, err = grpc_call(stub.ExchangeOAuth2CodeAndStore, request)
        if err:
            logger.error(err)
            return False

    print(f"Success            : {response.success}")
    print(f"Message            : {response.message}")
    print(f"Account Identifier : {response.account_identifier}")
    print(f"Token Hash         : {b64(response.token_hash)}")
    for key in response.server_ephemeral_public_key:
        print(f"Server Key [{key.key_id:>3}]  : {b64(key.public_key)}")
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
    shared.add_argument(
        "--platform", "-p", required=True, help="Platform name (e.g. gmail)"
    )
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
        "--code-verifier", metavar="VERIFIER", help="PKCE code verifier"
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
