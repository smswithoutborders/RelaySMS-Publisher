#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""CLI tool for testing gRPC flows."""

import argparse
import secrets
import sys

from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey

from lib_relaysms_payload_specs.generated import relaysms_spec_payload as rrs
from protos.v3 import publisher_pb2, publisher_pb2_grpc
from tests.helpers import (
    b64,
    b64d,
    build_v1_request_metadata,
    db_get,
    db_set,
    fetch_server_identity_public_key,
    grpc_call,
    grpc_channel,
    select_token_interactively,
)
from utils import get_logger

logger = get_logger("test_cli")


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------


def cmd_get_oauth2_url(args: argparse.Namespace) -> bool:
    """Fetch an OAuth2 authorization URL."""
    logger.info(
        "platform=%s grpc=%s:%d tls=%s", args.platform, args.host, args.port, args.tls
    )

    try:
        _, _, metadata = build_v1_request_metadata(
            rest_api=args.rest_api,
            method_name="/publisher.v3.Publisher/GetOAuth2AuthorizationUrl",
        )
    except Exception as e:
        logger.error("build_v1_request_metadata failed: %s", e)
        return False

    with grpc_channel(args.host, args.port, args.tls) as channel:
        stub = publisher_pb2_grpc.PublisherStub(channel)
        response, err = grpc_call(
            stub.GetOAuth2AuthorizationUrl,
            publisher_pb2.GetOAuth2AuthorizationUrlRequest(
                platform=args.platform,
                state=args.state or "",
                autogenerate_code_verifier=not args.no_auto_verifier,
            ),
            metadata=metadata,
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

    print(f"Authorization URL : {response.authorization_url}")
    print(f"State             : {response.state}")
    print(f"Code Verifier     : {response.code_verifier}")
    print(f"Client ID         : {response.client_id}")
    print(f"Scope             : {response.scope}")
    print(f"Redirect URL      : {response.redirect_url}")
    return True


def cmd_exchange_oauth2_code(args: argparse.Namespace) -> bool:
    """Exchange an OAuth2 code, decrypt the token, and store session data."""
    code_verifier = args.code_verifier or (db_get("oauth2") or {}).get(
        "code_verifier", ""
    )

    logger.info("platform=%s code=%s...", args.platform, args.code[:12])

    client_keypairs = [X25519PrivateKey.generate() for _ in range(256)]

    try:
        _, _, metadata = build_v1_request_metadata(
            rest_api=args.rest_api,
            method_name="/publisher.v3.Publisher/ExchangeOAuth2CodeAndStore",
        )
    except Exception as e:
        logger.error("build_v1_request_metadata failed: %s", e)
        return False

    with grpc_channel(args.host, args.port, args.tls) as channel:
        stub = publisher_pb2_grpc.PublisherStub(channel)
        response, err = grpc_call(
            stub.ExchangeOAuth2CodeAndStore,
            publisher_pb2.ExchangeOAuth2CodeAndStoreRequest(
                platform=args.platform,
                authorization_code=args.code,
                code_verifier=code_verifier,
                redirect_url=args.redirect_url or "",
                client_ephemeral_public_keys=[
                    publisher_pb2.PublicKey(
                        key_id=i, public_key=kp.public_key().public_bytes_raw()
                    )
                    for i, kp in enumerate(client_keypairs)
                ],
            ),
            metadata=metadata,
        )
        if err:
            logger.error(err)
            return False

    if not response.success:
        logger.error("exchange failed: %s", response.message)
        return False

    kid_index = response.key_id

    try:
        ss_kid_pk = fetch_server_identity_public_key(args.rest_api, kid_index)
    except Exception as e:
        logger.error("failed to fetch ss_kid_pk for kid_index=%d: %s", kid_index, e)
        return False

    es_entry = next(
        (k for k in response.server_ephemeral_public_keys if k.key_id == kid_index),
        None,
    )
    if not es_entry:
        logger.error("es_kid_pk not found for kid_index=%d", kid_index)
        return False

    try:
        raw_token = rrs.v1_token_decrypt_client(
            ec_kid=client_keypairs[kid_index].private_bytes_raw(),
            ss_kid_pk=ss_kid_pk,
            es_kid_pk=es_entry.public_key,
            key_id=kid_index,
            received_payload=response.token_ciphertext,
        )
    except Exception as e:
        logger.error("v1_token_decrypt_client failed: %s", e)
        return False

    logger.info("token decrypted using kid_index=%d", kid_index)

    tokens = db_get("tokens") or {}
    tokens[response.account_identifier] = {
        "platform": response.platform,
        "cat_id": response.cat_id,
        "account_identifier": response.account_identifier,
        "token": b64(raw_token),
        "token_id": b64(response.token_id),
        "server_ephemeral_public_keys": [
            {"key_id": k.key_id, "public_key": b64(k.public_key)}
            for k in response.server_ephemeral_public_keys
            if k.key_id != kid_index
        ],
        "client_ephemeral_keypairs": [
            {
                "key_id": i,
                "public_key": b64(kp.public_key().public_bytes_raw()),
                "private_key": b64(kp.private_bytes_raw()),
            }
            for i, kp in enumerate(client_keypairs)
            if i != kid_index
        ],
    }
    db_set("tokens", tokens)

    print(f"Success            : {response.success}")
    print(f"Message            : {response.message}")
    print(f"Account Identifier : {response.account_identifier}")
    print(f"Token ID           : {b64(response.token_id)}")
    print(f"Token              : {b64(raw_token, truncate=40)}")
    print(f"kid_index          : {kid_index}")
    return True


def cmd_revoke_oauth2_token(args: argparse.Namespace) -> bool:
    """Revoke a stored OAuth2 token."""
    tokens = db_get("tokens") or {}
    if not tokens:
        logger.error("no tokens found")
        return False

    if args.token:
        account_id = next(
            (ident for ident, d in tokens.items() if d.get("token") == args.token), None
        )
        if not account_id:
            logger.error("token not found")
            return False
    else:
        account_id = select_token_interactively(tokens)

    if not account_id:
        return False

    token_data = tokens[account_id]
    remaining_keypairs = token_data.get("client_ephemeral_keypairs", [])
    if not remaining_keypairs:
        logger.error("no client keypairs remaining for %s", account_id)
        return False

    kp = secrets.choice(remaining_keypairs)
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
        return False

    try:
        ss_kid_pk = fetch_server_identity_public_key(args.rest_api, kid_index)
    except Exception as e:
        logger.error("failed to fetch ss_kid_pk for kid_index=%d: %s", kid_index, e)
        return False

    try:
        encrypted_token = rrs.v1_token_encrypt_client(
            ec_kid=b64d(kp["private_key"]),
            ss_kid_pk=ss_kid_pk,
            es_kid_pk=b64d(es_entry["public_key"]),
            key_id=kid_index,
            token=b64d(token_data["token"]),
        )
    except Exception as e:
        logger.error("v1_token_encrypt_client failed: %s", e)
        return False

    try:
        _, _, metadata = build_v1_request_metadata(
            rest_api=args.rest_api,
            method_name="/publisher.v3.Publisher/RevokeOAuth2Token",
            payload=encrypted_token,
        )
    except Exception as e:
        logger.error("build_v1_request_metadata failed: %s", e)
        return False

    logger.info(
        "revoking token for %s platform=%s kid_index=%d",
        account_id,
        token_data["platform"],
        kid_index,
    )

    with grpc_channel(args.host, args.port, args.tls) as channel:
        stub = publisher_pb2_grpc.PublisherStub(channel)
        response, err = grpc_call(
            stub.RevokeOAuth2Token,
            publisher_pb2.RevokeOAuth2TokenRequest(
                token_id=b64d(token_data["token_id"]),
                key_id=kid_index,
            ),
            metadata=metadata,
        )
        if err:
            logger.error(err)
            return False

    if response.success:
        del tokens[account_id]
        db_set("tokens", tokens)
        logger.info("revoked and removed token for %s", account_id)

    print(f"Success : {response.success}")
    print(f"Message : {response.message}")
    return True


def cmd_get_pnba_code(args: argparse.Namespace) -> bool:
    """Request a PNBA code."""
    logger.info("platform=%s phone_number=%s", args.platform, args.phone_number)

    try:
        _, _, metadata = build_v1_request_metadata(
            rest_api=args.rest_api,
            method_name="/publisher.v3.Publisher/GetPNBACode",
        )
    except Exception as e:
        logger.error("build_v1_request_metadata failed: %s", e)
        return False

    with grpc_channel(args.host, args.port, args.tls) as channel:
        stub = publisher_pb2_grpc.PublisherStub(channel)
        response, err = grpc_call(
            stub.GetPNBACode,
            publisher_pb2.GetPNBACodeRequest(
                platform=args.platform,
                phone_number=args.phone_number,
                request_identifier=args.request_identifier or "",
            ),
            metadata=metadata,
        )
        if err:
            logger.error(err)
            return False

    print(f"Success : {response.success}")
    print(f"Message : {response.message}")
    return True


def cmd_exchange_pnba_code(args: argparse.Namespace) -> bool:
    """Exchange a PNBA code, decrypt the token, and store session data."""
    logger.info(
        "platform=%s phone=%s code=%s", args.platform, args.phone_number, args.code
    )

    client_keypairs = [X25519PrivateKey.generate() for _ in range(256)]

    try:
        _, _, metadata = build_v1_request_metadata(
            rest_api=args.rest_api,
            method_name="/publisher.v3.Publisher/ExchangePNBACodeAndStore",
        )
    except Exception as e:
        logger.error("build_v1_request_metadata failed: %s", e)
        return False

    with grpc_channel(args.host, args.port, args.tls) as channel:
        stub = publisher_pb2_grpc.PublisherStub(channel)
        response, err = grpc_call(
            stub.ExchangePNBACodeAndStore,
            publisher_pb2.ExchangePNBACodeAndStoreRequest(
                platform=args.platform,
                phone_number=args.phone_number,
                authorization_code=args.code,
                password=args.password or "",
                request_identifier=args.request_identifier or "",
                client_ephemeral_public_keys=[
                    publisher_pb2.PublicKey(
                        key_id=i, public_key=kp.public_key().public_bytes_raw()
                    )
                    for i, kp in enumerate(client_keypairs)
                ],
            ),
            metadata=metadata,
        )
        if err:
            logger.error(err)
            return False

    if not response.success:
        logger.error("exchange failed: %s", response.message)
        return False

    if response.two_step_verification_enabled:
        print("Two-step verification is enabled. Please run again with --password.")
        return True

    kid_index = response.key_id

    try:
        ss_kid_pk = fetch_server_identity_public_key(args.rest_api, kid_index)
    except Exception as e:
        logger.error("failed to fetch ss_kid_pk for kid_index=%d: %s", kid_index, e)
        return False

    es_entry = next(
        (k for k in response.server_ephemeral_public_keys if k.key_id == kid_index),
        None,
    )
    if not es_entry:
        logger.error("es_kid_pk not found for kid_index=%d", kid_index)
        return False

    try:
        raw_token = rrs.v1_token_decrypt_client(
            ec_kid=client_keypairs[kid_index].private_bytes_raw(),
            ss_kid_pk=ss_kid_pk,
            es_kid_pk=es_entry.public_key,
            key_id=kid_index,
            received_payload=response.token_ciphertext,
        )
    except Exception as e:
        logger.error("v1_token_decrypt_client failed: %s", e)
        return False

    logger.info("token decrypted using kid_index=%d", kid_index)

    tokens = db_get("tokens") or {}
    tokens[response.account_identifier] = {
        "platform": response.platform,
        "cat_id": response.cat_id,
        "account_identifier": response.account_identifier,
        "token": b64(raw_token),
        "token_id": b64(response.token_id),
        "server_ephemeral_public_keys": [
            {"key_id": k.key_id, "public_key": b64(k.public_key)}
            for k in response.server_ephemeral_public_keys
            if k.key_id != kid_index
        ],
        "client_ephemeral_keypairs": [
            {
                "key_id": i,
                "public_key": b64(kp.public_key().public_bytes_raw()),
                "private_key": b64(kp.private_bytes_raw()),
            }
            for i, kp in enumerate(client_keypairs)
            if i != kid_index
        ],
    }
    db_set("tokens", tokens)

    print(f"Success            : {response.success}")
    print(f"Message            : {response.message}")
    print(f"Account Identifier : {response.account_identifier}")
    print(f"Token ID           : {b64(response.token_id)}")
    print(f"Token              : {b64(raw_token, truncate=40)}")
    print(f"kid_index          : {kid_index}")
    return True


def cmd_revoke_pnba_token(args: argparse.Namespace) -> bool:
    """Revoke a stored PNBA token."""
    tokens = db_get("tokens") or {}
    if not tokens:
        logger.error("no tokens found")
        return False

    if args.token:
        account_id = next(
            (ident for ident, d in tokens.items() if d.get("token") == args.token), None
        )
        if not account_id:
            logger.error("token not found")
            return False
    else:
        account_id = select_token_interactively(tokens)

    if not account_id:
        return False

    token_data = tokens[account_id]
    remaining_keypairs = token_data.get("client_ephemeral_keypairs", [])
    if not remaining_keypairs:
        logger.error("no client keypairs remaining for %s", account_id)
        return False

    kp = secrets.choice(remaining_keypairs)
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
        return False

    try:
        ss_kid_pk = fetch_server_identity_public_key(args.rest_api, kid_index)
    except Exception as e:
        logger.error("failed to fetch ss_kid_pk for kid_index=%d: %s", kid_index, e)
        return False

    try:
        encrypted_token = rrs.v1_token_encrypt_client(
            ec_kid=b64d(kp["private_key"]),
            ss_kid_pk=ss_kid_pk,
            es_kid_pk=b64d(es_entry["public_key"]),
            key_id=kid_index,
            token=b64d(token_data["token"]),
        )
    except Exception as e:
        logger.error("v1_token_encrypt_client failed: %s", e)
        return False

    try:
        _, _, metadata = build_v1_request_metadata(
            rest_api=args.rest_api,
            method_name="/publisher.v3.Publisher/RevokePNBAToken",
            payload=encrypted_token,
        )
    except Exception as e:
        logger.error("build_v1_request_metadata failed: %s", e)
        return False

    logger.info(
        "revoking token for %s platform=%s kid_index=%d",
        account_id,
        token_data["platform"],
        kid_index,
    )

    with grpc_channel(args.host, args.port, args.tls) as channel:
        stub = publisher_pb2_grpc.PublisherStub(channel)
        response, err = grpc_call(
            stub.RevokePNBAToken,
            publisher_pb2.RevokePNBATokenRequest(
                token_id=b64d(token_data["token_id"]),
                key_id=kid_index,
            ),
            metadata=metadata,
        )
        if err:
            logger.error(err)
            return False

    if response.success:
        del tokens[account_id]
        db_set("tokens", tokens)
        logger.info("revoked and removed token for %s", account_id)

    print(f"Success : {response.success}")
    print(f"Message : {response.message}")
    return True


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

COMMANDS = {
    "get-oauth2-url": cmd_get_oauth2_url,
    "exchange-oauth2-code": cmd_exchange_oauth2_code,
    "revoke-oauth2-token": cmd_revoke_oauth2_token,
    "get-pnba-code": cmd_get_pnba_code,
    "exchange-pnba-code": cmd_exchange_pnba_code,
    "revoke-pnba-token": cmd_revoke_pnba_token,
}


def build_parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(
        description="CLI test tool for gRPC flows.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python -m tests.client get-oauth2-url --platform gmail
  python -m tests.client exchange-oauth2-code --platform gmail --code AUTH_CODE
  python -m tests.client revoke-oauth2-token
  python -m tests.client get-pnba-code --platform telegram --phone-number +123456789
  python -m tests.client exchange-pnba-code --platform telegram --phone-number +123456789 --code 12345
  python -m tests.client revoke-pnba-token
        """,
    )

    shared = argparse.ArgumentParser(add_help=False)
    shared.add_argument(
        "--host", default="127.0.0.1", help="gRPC host (default: 127.0.0.1)"
    )
    shared.add_argument(
        "--port", type=int, default=6000, help="gRPC port (default: 6000)"
    )
    shared.add_argument("--tls", action="store_true", help="Use TLS")
    shared.add_argument("--platform", "-p", help="Platform name (e.g. gmail)")
    shared.add_argument("--state", help="OAuth2 state parameter")
    shared.add_argument(
        "--rest-api",
        default="http://localhost:16000",
        metavar="URL",
        help="REST API base URL (default: http://localhost:16000)",
    )
    shared.add_argument("--phone-number", help="PNBA phone number")
    shared.add_argument("--request-identifier", help="Optional request identifier")

    sub = root.add_subparsers(dest="command", metavar="COMMAND", required=True)

    p_get = sub.add_parser(
        "get-oauth2-url", parents=[shared], help="Fetch OAuth2 authorization URL"
    )
    p_get.add_argument(
        "--no-auto-verifier",
        action="store_true",
        help="Disable auto PKCE code verifier",
    )

    p_exchange = sub.add_parser(
        "exchange-oauth2-code", parents=[shared], help="Exchange OAuth2 code for token"
    )
    p_exchange.add_argument("--code", required=True, help="Authorization code")
    p_exchange.add_argument(
        "--code-verifier",
        metavar="VERIFIER",
        help="PKCE code verifier (falls back to db.json)",
    )
    p_exchange.add_argument("--redirect-url", metavar="URL", help="Redirect URL")

    p_revoke = sub.add_parser(
        "revoke-oauth2-token", parents=[shared], help="Revoke a stored token"
    )
    p_revoke.add_argument(
        "--token",
        metavar="TOKEN",
        help="Raw token (base64) to revoke, omit for interactive prompt",
    )

    _ = sub.add_parser("get-pnba-code", parents=[shared], help="Request PNBA code")

    p_exchange_pnba = sub.add_parser(
        "exchange-pnba-code", parents=[shared], help="Exchange PNBA code for token"
    )
    p_exchange_pnba.add_argument("--code", required=True, help="Authorization code")
    p_exchange_pnba.add_argument("--password", help="Two-step verification password")

    p_revoke_pnba = sub.add_parser(
        "revoke-pnba-token", parents=[shared], help="Revoke a stored PNBA token"
    )
    p_revoke_pnba.add_argument(
        "--token",
        metavar="TOKEN",
        help="Raw token (base64) to revoke, omit for interactive prompt",
    )

    return root


def main():
    parser = build_parser()
    args = parser.parse_args()
    sys.exit(0 if COMMANDS[args.command](args) else 1)


if __name__ == "__main__":
    main()
