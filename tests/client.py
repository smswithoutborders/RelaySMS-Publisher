#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""CLI tool for testing gRPC flows."""

import json
import random
import secrets
import sys
import time

import click
import requests
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey

from lib_relaysms_payload_specs.generated import relaysms_spec_payload as rrs
from protos.v3 import publisher_pb2, publisher_pb2_grpc
from tests.helpers import (
    b64,
    b64d,
    build_v1_request_metadata,
    db_get,
    db_set,
    fetch_platform_info,
    fetch_server_identity_public_key,
    grpc_call,
    grpc_channel,
    select_token_interactively,
)
from utils import get_logger

logger = get_logger("test_cli")


def shared_options(f):
    """A blanket decorator supplying all parameters used across various gRPC/REST endpoints."""
    f = click.option(
        "--host", default="127.0.0.1", show_default=True, help="gRPC host."
    )(f)
    f = click.option(
        "--port", type=int, default=6000, show_default=True, help="gRPC port."
    )(f)
    f = click.option("--tls", is_flag=True, help="Use TLS.")(f)
    f = click.option(
        "--rest-api",
        default="http://localhost:16000",
        show_default=True,
        metavar="URL",
        help="REST API base URL.",
    )(f)
    f = click.option("--platform", "-p", help="Platform name (e.g. gmail).")(f)
    f = click.option("--state", help="OAuth2 state parameter.")(f)
    f = click.option("--code-verifier", help="PKCE code verifier.")(f)
    f = click.option("--redirect-url", help="OAuth2 redirect URL.")(f)
    f = click.option("--phone-number", help="PNBA phone number.")(f)
    f = click.option("--request-identifier", help="Optional request identifier.")(f)
    f = click.option("--token", help="Raw token (base64) to use.")(f)
    return f


@click.group(
    epilog="""
Examples:\n
  python -m tests.client get-oauth2-url --platform gmail\n
  python -m tests.client exchange-oauth2-code --platform gmail --code AUTH_CODE\n
  python -m tests.client revoke-oauth2-token\n
  python -m tests.client get-pnba-code --platform telegram --phone-number +123456789\n
  python -m tests.client exchange-pnba-code --platform telegram --phone-number +123456789 --code 12345\n
  python -m tests.client revoke-pnba-token\n
  python -m tests.client sync-keys\n
  python -m tests.client send --platform gmail --address +237123456789 --to friend@example.com --subject "Hello" --body "Test"\n
  python -m tests.client send --platform telegram --address +237123456789 --to +237123456789 --body "Hi there"\n
  python -m tests.client send --platform gmail --address +237123456789 --to friend@example.com --subject "Hello" --body "See attached" --attachment ./file.pdf\n
  python -m tests.client send --platform gmail --address +237123456789 --to friend@example.com --subject "Hello" --body "See attached" --attachment ./file.pdf --interval 2.5 --shuffle\n
  python -m tests.client send --platform gmail --address +237123456789 --to friend@example.com --body "Dry run" --attachment ./file.pdf --dry-run --shuffle\n
"""
)
def cli():
    """CLI test tool for gRPC flows."""
    pass


@cli.command("get-oauth2-url")
@shared_options
@click.option(
    "--no-auto-verifier", is_flag=True, help="Disable auto PKCE code verifier."
)
def cmd_get_oauth2_url(
    host,
    port,
    tls,
    rest_api,
    platform,
    state,
    no_auto_verifier,
    request_identifier,
    code_verifier,
    redirect_url,
    **_,
):
    """Fetch an OAuth2 authorization URL."""
    logger.info("platform=%s | grpc=%s:%d | tls=%s", platform, host, port, tls)

    try:
        _, _, metadata = build_v1_request_metadata(
            rest_api=rest_api,
            method_name="/publisher.v3.Publisher/GetOAuth2AuthorizationUrl",
        )
    except Exception as e:
        logger.error("build_v1_request_metadata failed: %s", e)
        sys.exit(1)

    with grpc_channel(host, port, tls) as channel:
        stub = publisher_pb2_grpc.PublisherStub(channel)
        response, err = grpc_call(
            stub.GetOAuth2AuthorizationUrl,
            publisher_pb2.GetOAuth2AuthorizationUrlRequest(
                platform=platform,
                state=state,
                code_verifier=code_verifier,
                autogenerate_code_verifier=not no_auto_verifier,
                redirect_url=redirect_url,
                request_identifier=request_identifier,
            ),
            metadata=metadata,
        )
        if err:
            logger.error(err)
            sys.exit(1)

    db_set(
        "oauth2",
        {
            "platform": platform,
            "state": response.state,
            "code_verifier": response.code_verifier,
            "client_id": response.client_id,
            "scope": response.scope,
            "redirect_url": response.redirect_url,
        },
    )

    click.echo(f"Authorization URL : {response.authorization_url}")
    click.echo(f"State             : {response.state}")
    click.echo(f"Code Verifier     : {response.code_verifier}")
    click.echo(f"Client ID         : {response.client_id}")
    click.echo(f"Scope             : {response.scope}")
    click.echo(f"Redirect URL      : {response.redirect_url}")


@cli.command("exchange-oauth2-code")
@shared_options
@click.option("--code", required=True, help="Authorization code.")
def cmd_exchange_oauth2_code(
    host,
    port,
    tls,
    rest_api,
    platform,
    code,
    code_verifier,
    redirect_url,
    request_identifier,
    **_,
):
    """Exchange an OAuth2 code, decrypt the token, and store session data."""
    fallback_verifier = code_verifier or (db_get("oauth2") or {}).get(
        "code_verifier", ""
    )

    logger.info("platform=%s | code=%s...", platform, code[:12] if code else "")

    client_keypairs = [X25519PrivateKey.generate() for _ in range(256)]

    try:
        _, _, metadata = build_v1_request_metadata(
            rest_api=rest_api,
            method_name="/publisher.v3.Publisher/ExchangeOAuth2CodeAndStore",
        )
    except Exception as e:
        logger.error("build_v1_request_metadata failed: %s", e)
        sys.exit(1)

    with grpc_channel(host, port, tls) as channel:
        stub = publisher_pb2_grpc.PublisherStub(channel)
        response, err = grpc_call(
            stub.ExchangeOAuth2CodeAndStore,
            publisher_pb2.ExchangeOAuth2CodeAndStoreRequest(
                platform=platform,
                authorization_code=code,
                code_verifier=fallback_verifier,
                redirect_url=redirect_url,
                request_identifier=request_identifier,
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
            sys.exit(1)

    if not response.success:
        logger.error("exchange failed: %s", response.message)
        sys.exit(1)

    kid_index = response.key_id

    try:
        ss_kid_pk = fetch_server_identity_public_key(rest_api, kid_index)
    except Exception as e:
        logger.error("failed to fetch ss_kid_pk for kid_index=%d: %s", kid_index, e)
        sys.exit(1)

    es_entry = next(
        (k for k in response.server_ephemeral_public_keys if k.key_id == kid_index),
        None,
    )
    if not es_entry:
        logger.error("es_kid_pk not found for kid_index=%d", kid_index)
        sys.exit(1)

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
        sys.exit(1)

    logger.info("token decrypted using kid_index=%d", kid_index)

    tokens = db_get("tokens") or {}
    tokens[response.account_identifier] = {
        "platform": response.platform,
        "cat_id": response.cat_id,
        "account_identifier": response.account_identifier,
        "token": b64(raw_token),
        "token_id": response.token_id,
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

    click.echo(f"Success            : {response.success}")
    click.echo(f"Message            : {response.message}")
    click.echo(f"Account Identifier : {response.account_identifier}")
    click.echo(f"Token ID           : {response.token_id}")
    click.echo(f"Token              : {b64(raw_token, truncate=40)}")
    click.echo(f"kid_index          : {kid_index}")


@cli.command("revoke-oauth2-token")
@shared_options
def cmd_revoke_oauth2_token(host, port, tls, rest_api, token, **_):
    """Revoke a stored OAuth2 token."""
    tokens = db_get("tokens") or {}
    if not tokens:
        logger.error("no tokens found")
        sys.exit(1)

    if token:
        account_id = next(
            (ident for ident, d in tokens.items() if d.get("token") == token), None
        )
        if not account_id:
            logger.error("token not found")
            sys.exit(1)
    else:
        account_id = select_token_interactively(tokens)

    if not account_id:
        sys.exit(1)

    token_data = tokens[account_id]
    remaining_keypairs = token_data.get("client_ephemeral_keypairs", [])
    if not remaining_keypairs:
        logger.error("no client keypairs remaining for %s", account_id)
        sys.exit(1)

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
        sys.exit(1)

    try:
        ss_kid_pk = fetch_server_identity_public_key(rest_api, kid_index)
    except Exception as e:
        logger.error("failed to fetch ss_kid_pk for kid_index=%d: %s", kid_index, e)
        sys.exit(1)

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
        sys.exit(1)

    try:
        _, _, metadata = build_v1_request_metadata(
            rest_api=rest_api,
            method_name="/publisher.v3.Publisher/RevokeOAuth2Token",
            payload=encrypted_token,
        )
    except Exception as e:
        logger.error("build_v1_request_metadata failed: %s", e)
        sys.exit(1)

    logger.info(
        "revoking token for %s platform=%s kid_index=%d",
        account_id,
        token_data["platform"],
        kid_index,
    )

    with grpc_channel(host, port, tls) as channel:
        stub = publisher_pb2_grpc.PublisherStub(channel)
        response, err = grpc_call(
            stub.RevokeOAuth2Token,
            publisher_pb2.RevokeOAuth2TokenRequest(
                token_id=token_data["token_id"], key_id=kid_index
            ),
            metadata=metadata,
        )
        if err:
            logger.error(err)
            sys.exit(1)

    if response.success:
        del tokens[account_id]
        db_set("tokens", tokens)
        logger.info("revoked and removed token for %s", account_id)

    click.echo(f"Success : {response.success}")
    click.echo(f"Message : {response.message}")


@cli.command("get-pnba-code")
@shared_options
@click.option("--auth-channel", help="The medium used to receive the code.")
def cmd_get_pnba_code(
    host,
    port,
    tls,
    rest_api,
    platform,
    phone_number,
    request_identifier,
    auth_channel,
    **_,
):
    """Request a PNBA code."""
    logger.info("platform=%s | phone_number=%s", platform, phone_number)

    try:
        _, _, metadata = build_v1_request_metadata(
            rest_api=rest_api,
            method_name="/publisher.v3.Publisher/GetPNBACode",
        )
    except Exception as e:
        logger.error("build_v1_request_metadata failed: %s", e)
        sys.exit(1)

    with grpc_channel(host, port, tls) as channel:
        stub = publisher_pb2_grpc.PublisherStub(channel)
        response, err = grpc_call(
            stub.GetPNBACode,
            publisher_pb2.GetPNBACodeRequest(
                platform=platform,
                phone_number=phone_number,
                request_identifier=request_identifier,
                channel=auth_channel,
            ),
            metadata=metadata,
        )
        if err:
            logger.error(err)
            sys.exit(1)

    click.echo(f"Success : {response.success}")
    click.echo(f"Message : {response.message}")


@cli.command("exchange-pnba-code")
@shared_options
@click.option("--code", required=True, help="Authorization code.")
@click.option("--password", help="Two-step verification password.")
@click.option("--auth-channel", help="The medium used to receive the code.")
def cmd_exchange_pnba_code(
    host,
    port,
    tls,
    rest_api,
    platform,
    phone_number,
    request_identifier,
    code,
    password,
    auth_channel,
    **_,
):
    """Exchange a PNBA code, decrypt the token, and store session data."""
    logger.info("platform=%s | phone=%s | code=%s", platform, phone_number, code)

    client_keypairs = [X25519PrivateKey.generate() for _ in range(256)]

    try:
        _, _, metadata = build_v1_request_metadata(
            rest_api=rest_api,
            method_name="/publisher.v3.Publisher/ExchangePNBACodeAndStore",
        )
    except Exception as e:
        logger.error("build_v1_request_metadata failed: %s", e)
        sys.exit(1)

    with grpc_channel(host, port, tls) as channel:
        stub = publisher_pb2_grpc.PublisherStub(channel)
        response, err = grpc_call(
            stub.ExchangePNBACodeAndStore,
            publisher_pb2.ExchangePNBACodeAndStoreRequest(
                platform=platform,
                phone_number=phone_number,
                authorization_code=code,
                password=password,
                request_identifier=request_identifier,
                client_ephemeral_public_keys=[
                    publisher_pb2.PublicKey(
                        key_id=i, public_key=kp.public_key().public_bytes_raw()
                    )
                    for i, kp in enumerate(client_keypairs)
                ],
                channel=auth_channel,
            ),
            metadata=metadata,
        )
        if err:
            logger.error(err)
            sys.exit(1)

    if not response.success:
        logger.error("exchange failed: %s", response.message)
        sys.exit(1)

    if response.two_step_verification_enabled:
        click.echo(
            "Two-step verification is enabled. Please run again with --password."
        )
        return

    kid_index = response.key_id

    try:
        ss_kid_pk = fetch_server_identity_public_key(rest_api, kid_index)
    except Exception as e:
        logger.error("failed to fetch ss_kid_pk for kid_index=%d: %s", kid_index, e)
        sys.exit(1)

    es_entry = next(
        (k for k in response.server_ephemeral_public_keys if k.key_id == kid_index),
        None,
    )
    if not es_entry:
        logger.error("es_kid_pk not found for kid_index=%d", kid_index)
        sys.exit(1)

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
        sys.exit(1)

    logger.info("token decrypted using kid_index=%d", kid_index)

    tokens = db_get("tokens") or {}
    tokens[response.account_identifier] = {
        "platform": response.platform,
        "cat_id": response.cat_id,
        "account_identifier": response.account_identifier,
        "token": b64(raw_token),
        "token_id": response.token_id,
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

    click.echo(f"Success            : {response.success}")
    click.echo(f"Message            : {response.message}")
    click.echo(f"Account Identifier : {response.account_identifier}")
    click.echo(f"Token ID           : {response.token_id}")
    click.echo(f"Token              : {b64(raw_token, truncate=40)}")
    click.echo(f"kid_index          : {kid_index}")


@cli.command("revoke-pnba-token")
@shared_options
def cmd_revoke_pnba_token(host, port, tls, rest_api, token, **_):
    """Revoke a stored PNBA token."""
    tokens = db_get("tokens") or {}
    if not tokens:
        logger.error("no tokens found")
        sys.exit(1)

    if token:
        account_id = next(
            (ident for ident, d in tokens.items() if d.get("token") == token), None
        )
        if not account_id:
            logger.error("token not found")
            sys.exit(1)
    else:
        account_id = select_token_interactively(tokens)

    if not account_id:
        sys.exit(1)

    token_data = tokens[account_id]
    remaining_keypairs = token_data.get("client_ephemeral_keypairs", [])
    if not remaining_keypairs:
        logger.error("no client keypairs remaining for %s", account_id)
        sys.exit(1)

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
        sys.exit(1)

    try:
        ss_kid_pk = fetch_server_identity_public_key(rest_api, kid_index)
    except Exception as e:
        logger.error("failed to fetch ss_kid_pk for kid_index=%d: %s", kid_index, e)
        sys.exit(1)

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
        sys.exit(1)

    try:
        _, _, metadata = build_v1_request_metadata(
            rest_api=rest_api,
            method_name="/publisher.v3.Publisher/RevokePNBAToken",
            payload=encrypted_token,
        )
    except Exception as e:
        logger.error("build_v1_request_metadata failed: %s", e)
        sys.exit(1)

    logger.info(
        "revoking token for %s platform=%s kid_index=%d",
        account_id,
        token_data["platform"],
        kid_index,
    )

    with grpc_channel(host, port, tls) as channel:
        stub = publisher_pb2_grpc.PublisherStub(channel)
        response, err = grpc_call(
            stub.RevokePNBAToken,
            publisher_pb2.RevokePNBATokenRequest(
                token_id=token_data["token_id"], key_id=kid_index
            ),
            metadata=metadata,
        )
        if err:
            logger.error(err)
            sys.exit(1)

    if response.success:
        del tokens[account_id]
        db_set("tokens", tokens)
        logger.info("revoked and removed token for %s", account_id)

    click.echo(f"Success : {response.success}")
    click.echo(f"Message : {response.message}")


@cli.command("sync-keys")
@shared_options
def cmd_sync_keys(host, port, tls, rest_api, token, **_):
    """Sync client and server key pools for a token."""
    tokens = db_get("tokens") or {}
    if not tokens:
        logger.error("no tokens found")
        sys.exit(1)

    if token:
        account_id = next(
            (ident for ident, d in tokens.items() if d.get("token") == token), None
        )
        if not account_id:
            logger.error("token not found")
            sys.exit(1)
    else:
        account_id = select_token_interactively(tokens)

    if not account_id:
        sys.exit(1)

    token_data = tokens[account_id]
    remaining_keypairs = token_data.get("client_ephemeral_keypairs", [])
    if not remaining_keypairs:
        logger.error("no client keypairs remaining for %s", account_id)
        sys.exit(1)

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
        sys.exit(1)

    try:
        ss_kid_pk = fetch_server_identity_public_key(rest_api, kid_index)
    except Exception as e:
        logger.error("failed to fetch ss_kid_pk for kid_index=%d: %s", kid_index, e)
        sys.exit(1)

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
        sys.exit(1)

    try:
        _, _, metadata = build_v1_request_metadata(
            rest_api=rest_api,
            method_name="/publisher.v3.Publisher/SyncKeys",
            payload=encrypted_token,
        )
    except Exception as e:
        logger.error("build_v1_request_metadata failed: %s", e)
        sys.exit(1)

    logger.info(
        "syncing keys for %s platform=%s kid_index=%d",
        account_id,
        token_data["platform"],
        kid_index,
    )

    new_client_keypairs = [X25519PrivateKey.generate() for _ in range(256)]

    with grpc_channel(host, port, tls) as channel:
        stub = publisher_pb2_grpc.PublisherStub(channel)
        response, err = grpc_call(
            stub.SyncKeys,
            publisher_pb2.SyncKeysRequest(
                token_id=token_data["token_id"],
                key_id=kid_index,
                client_ephemeral_public_keys=[
                    publisher_pb2.PublicKey(
                        key_id=i, public_key=nkp.public_key().public_bytes_raw()
                    )
                    for i, nkp in enumerate(new_client_keypairs)
                ],
            ),
            metadata=metadata,
        )
        if err:
            logger.error(err)
            sys.exit(1)

    if not response.success:
        logger.error("sync failed: %s", response.message)
        sys.exit(1)

    tokens[account_id].update(
        {
            "server_ephemeral_public_keys": [
                {"key_id": k.key_id, "public_key": b64(k.public_key)}
                for k in response.server_ephemeral_public_keys
            ],
            "client_ephemeral_keypairs": [
                {
                    "key_id": i,
                    "public_key": b64(nkp.public_key().public_bytes_raw()),
                    "private_key": b64(nkp.private_bytes_raw()),
                }
                for i, nkp in enumerate(new_client_keypairs)
            ],
        }
    )
    db_set("tokens", tokens)

    click.echo(f"Success    : {response.success}")
    click.echo(f"Message    : {response.message}")


@cli.command("send")
@shared_options
@click.option(
    "--address",
    required=True,
    metavar="MSISDN",
    help="Sender's phone number (e.g. +237123456789).",
)
@click.option("--to", metavar="ADDRESS", help="Recipient address (email or phone).")
@click.option(
    "--subject",
    metavar="TEXT",
    help="Message subject (optional, email platforms only).",
)
@click.option("--body", required=True, metavar="TEXT", help="Message body.")
@click.option(
    "--attachment", type=click.Path(exists=True), help="Path to attachment file."
)
@click.option(
    "--interval",
    type=float,
    default=1.0,
    show_default=True,
    help="Seconds between segment transmissions.",
)
@click.option(
    "--shuffle",
    is_flag=True,
    help="Send segments in random order to simulate out-of-order delivery.",
)
@click.option(
    "--dry-run", is_flag=True, help="Print all segments instead of sending them."
)
def cmd_send(
    rest_api,
    platform,
    address,
    to,
    subject,
    body,
    token,
    attachment,
    interval,
    shuffle,
    dry_run,
    **_,
):
    """Publish an encrypted message to any platform via the REST API."""

    if not platform:
        logger.error("--platform is required for this command.")
        sys.exit(1)

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

    has_attachment = bool(attachment)

    if has_attachment:
        eligible_keypairs = [k for k in remaining_keypairs if k["key_id"] <= 15]
        if not eligible_keypairs:
            logger.error(
                "no eligible keypairs (key_id <= 15) remaining for %s.", account_id
            )
            sys.exit(1)
    else:
        eligible_keypairs = remaining_keypairs

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
        "platform=%s | shortcode=%s | cat_id=%s | key_id=%d",
        platform_info["name"],
        platform_info["shortcode"],
        platform_info["cat_id"],
        kid_index,
    )

    attachment_bytes = None
    if attachment:
        try:
            with open(attachment, "rb") as f:
                attachment_bytes = f.read()
            logger.info(
                "attachment loaded: %d bytes from %s", len(attachment_bytes), attachment
            )
        except Exception as e:
            logger.error("failed to read attachment: %s", e)
            sys.exit(1)

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

    len_att = len(attachment_bytes) if attachment_bytes else 0
    sess_id = secrets.randbelow(128) if has_attachment else None

    try:
        payload = rrs.V1Payloads(
            contents=encrypted_content,
            k_id=kid_index,
            len_att=len_att,
            t_id=token_data["token_id"],
            sess_id=sess_id,
        )
        if has_attachment:
            segments = payload.split(rrs.Transports.SMS)
            segments_b64 = [seg.decode() for seg in segments]
        else:
            raw = payload.serialize_without_attachment()
            segments_b64 = [b64(raw, urlsafe=False)]
    except Exception as e:
        logger.exception("payload build/split failed: %s", e)
        sys.exit(1)

    url = f"{rest_api}/v1/publications"

    if dry_run:
        click.echo(f"--- dry run: would POST {len(segments_b64)} segment(s) to {url}")
        click.echo(f"    attachment : {attachment or 'none'} ({len_att} bytes)")
        click.echo(f"    sess_id    : {sess_id}")
        click.echo(f"    interval   : {interval}s")
        click.echo(f"    shuffle    : {shuffle}")
        click.echo()
        order = list(range(len(segments_b64)))
        if shuffle:
            random.shuffle(order)
            click.echo(f"    send order : {order}")
        for pos, idx in enumerate(order):
            req_body = {"address": address, "text": segments_b64[idx]}
            click.echo(f"  segment [{pos + 1}/{len(order)}] (seg_num={idx}):")
            click.echo(json.dumps(req_body, indent=4))
        return

    logger.info(
        "publishing platform=%s | account=%s | kid_index=%d | segments=%d | shuffle=%s",
        p_lower,
        account_id,
        kid_index,
        len(segments_b64),
        shuffle,
    )

    order = list(range(len(segments_b64)))
    if shuffle:
        random.shuffle(order)
        logger.info("shuffled send order: %s", order)

    for pos, idx in enumerate(order):
        req_body = {"address": address, "text": segments_b64[idx]}
        logger.info("sending segment [%d/%d] seg_num=%d", pos + 1, len(order), idx)
        try:
            resp = requests.post(url, json=req_body, timeout=30)
            resp.raise_for_status()
        except requests.exceptions.HTTPError as e:
            logger.error("HTTP error on seg %d: %s -- %s", idx, e, resp.text)
            sys.exit(1)
        except Exception as e:
            logger.error("request failed on seg %d: %s", idx, e)
            sys.exit(1)

        result = resp.json()
        click.echo(
            f"  segment [{pos + 1}/{len(order)}] seg_num={idx} | "
            f"status={resp.status_code} | message={result.get('message', '')}"
        )

        if pos < len(order) - 1:
            time.sleep(interval)

    token_data["client_ephemeral_keypairs"] = [
        k for k in token_data["client_ephemeral_keypairs"] if k["key_id"] != kid_index
    ]
    token_data["server_ephemeral_public_keys"] = [
        k
        for k in token_data["server_ephemeral_public_keys"]
        if k["key_id"] != kid_index
    ]
    db_set("tokens", tokens)

    click.echo(f"\nDone. {len(order)} segment(s) sent.")


if __name__ == "__main__":
    cli()
