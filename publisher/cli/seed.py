# SPDX-License-Identifier: GPL-3.0-only
"""Fill the database with random data for development and demos."""

import datetime
import random
import secrets

import click
import phonenumbers
from sqlalchemy import insert

from publisher import credentials
from publisher.credentials import parse_scopes
from publisher.db import get_session
from publisher.db.types import utc_now
from publisher.gateway_clients import manager as gateway_clients
from publisher.models import platform_adapter as platform_adapters
from publisher.models.credential import ALL_SCOPES, Scope
from publisher.models.platform_adapter import (
    OAUTH2,
    PNBA,
    PROTOCOL_NAMES,
    PlatformAdapter,
)
from publisher.models.publication_stats import PublicationStats
from publisher.platforms.manager import adapter_id

PLATFORMS = ("gmail", "twitter", "telegram", "slack", "bluesky", "mastodon")
PROTOCOLS = ("https", "smtp", "sms")
COUNTRIES = ("CM", "NG", "GH", "KE", "UG", "ZA", "US", "FR", "DE", "GB")
FAILURE_REASONS = (
    "Token not found",
    "Token hash not found",
    "Server ephemeral key already used or missing",
    "Invalid payload structure.",
    "Payload is not valid base64.",
    "Invalid tag for offline content.",
    "unexpected_error",
)
FAILURE_RATE = 0.2
DISABLED_RATE = 0.1
BATCH_SIZE = 1000
# name, display name, protocol, category (0 email, 1 message, 2 text).
ADAPTERS = (
    ("gmail", "Gmail", OAUTH2, 0),
    ("twitter", "X", OAUTH2, 2),
    ("telegram", "Telegram", PNBA, 1),
    ("slack", "Slack", OAUTH2, 1),
    ("bluesky", "Bluesky", OAUTH2, 2),
    ("mastodon", "Mastodon", OAUTH2, 2),
)


def _random_stat(now: datetime.datetime, days: int) -> dict:
    failed = random.random() < FAILURE_RATE
    return dict(
        status="failed" if failed else "published",
        protocol=random.choice(PROTOCOLS),
        # Some failures happen before the platform is known.
        platform_name=(
            None if failed and random.random() < 0.3 else random.choice(PLATFORMS)
        ),
        country_code=random.choice(COUNTRIES),
        failure_reason=random.choice(FAILURE_REASONS) if failed else None,
        created_at=now - datetime.timedelta(seconds=random.uniform(0, days * 86400)),
    )


def _random_scopes() -> frozenset[Scope]:
    # Retries until the scopes are valid together and short of administrator.
    while True:
        picked = random.sample(list(Scope), random.randint(1, len(Scope) - 1))
        try:
            scopes = parse_scopes(picked)
        except credentials.InvalidCredentialError:
            continue
        if scopes != ALL_SCOPES:
            return scopes


@click.group()
def cli():
    """Seed random development data."""


@cli.command()
@click.option("--count", default=1000, show_default=True, help="Rows to add.")
@click.option(
    "--days", default=90, show_default=True, help="Spread rows over the last N days."
)
def stats(count, days):
    """Add random publication stats."""
    now = utc_now()
    with get_session() as db:
        for start in range(0, count, BATCH_SIZE):
            rows = [
                _random_stat(now, days) for _ in range(min(BATCH_SIZE, count - start))
            ]
            db.execute(insert(PublicationStats), rows)

    click.echo(f"Added {count} publication stats over the last {days} days.")


@cli.command()
@click.option("--count", default=5, show_default=True, help="Credentials to add.")
def creds(count):
    """Add credentials with random scopes, never every scope."""
    with get_session() as db:
        created = [
            credentials.create(db, f"seed-{secrets.token_hex(4)}", _random_scopes())
            for _ in range(count)
        ]
        lines = [
            f"{credential.username}  {password}  {','.join(sorted(credential.scopes))}"
            for credential, password in created
        ]

    click.echo("\n".join(lines))
    click.echo(f"Added {count} credentials. Passwords are shown only here.", err=True)


@cli.command()
def platforms():
    """Register the well-known adapters, without their files."""
    added = []
    with get_session() as db:
        for name, display_name, proto_id, cat_id in ADAPTERS:
            if platform_adapters.find(
                db, name=name, proto_id=proto_id, include_disabled=True
            ):
                continue
            protocol = PROTOCOL_NAMES[proto_id]
            url = f"https://github.com/smswithoutborders/{name}-{protocol}-adapter"
            db.add(
                PlatformAdapter(
                    id=adapter_id(url),
                    source_url=url,
                    # No tag, so platforms update installs the newest release.
                    commit=secrets.token_hex(20),
                    name=name,
                    display_name=display_name,
                    proto_id=proto_id,
                    cat_id=cat_id,
                )
            )
            added.append(name)

    click.echo(f"Added {len(added)} adapter(s): {', '.join(added) or 'none'}.")
    if added:
        click.echo(
            "They have no files. Run platforms update <NAME> to install one.",
            err=True,
        )


def _random_mobile(region: str) -> str:
    example = phonenumbers.example_number_for_type(
        region, phonenumbers.PhoneNumberType.MOBILE
    )
    assert example is not None, f"phonenumbers has no mobile example for {region}"
    digits = str(example.national_number)
    tail = "".join(random.choices("0123456789", k=4))
    return f"+{example.country_code}{digits[:-4]}{tail}"


@cli.command(name="gateway-clients")
@click.option("--count", default=10, show_default=True, help="Clients to add.")
def gateway_clients_command(count):
    """Add gateway clients with random, resolvable numbers."""
    added = 0
    with get_session() as db:
        while added < count:
            msisdn = _random_mobile(random.choice(COUNTRIES))
            suggestion = gateway_clients.suggest(msisdn)
            # Picks for the ambiguous ones, as an administrator would.
            candidate = suggestion.candidates[0]
            try:
                client = gateway_clients.create(
                    db,
                    msisdn,
                    random.sample(PROTOCOLS, random.randint(1, len(PROTOCOLS))),
                    operator=suggestion.operator or candidate.network,
                    operator_code=candidate.operator_code,
                )
            except gateway_clients.GatewayClientExistsError:
                continue
            if random.random() < DISABLED_RATE:
                gateway_clients.set_enabled(db, client, False)
            added += 1

    click.echo(f"Added {added} gateway clients.")
