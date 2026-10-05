# SPDX-License-Identifier: GPL-3.0-only
"""Fill the database with random data for development and demos."""

import datetime
import random
import secrets

import click
from sqlalchemy import insert

from publisher import credentials
from publisher.credentials import parse_scopes
from publisher.db import get_session
from publisher.db.types import utc_now
from publisher.log import setup_logging
from publisher.models.credential import ALL_SCOPES, Scope
from publisher.models.publication_stats import PublicationStats

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
BATCH_SIZE = 1000


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


if __name__ == "__main__":
    setup_logging()
    cli()
