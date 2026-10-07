# SPDX-License-Identifier: GPL-3.0-only

import click

from publisher.cli.db import session
from publisher.cli.output import print_table
from publisher.gateway_clients import manager, mcc_mnc
from publisher.models import gateway_client as gateway_clients


def _split(protocols):
    return [p.strip() for p in protocols.split(",") if p.strip()]


@click.group()
def cli():
    """Manage gateway clients."""


@cli.command()
@click.option("--msisdn", required=True, help="MSISDN of the gateway client.")
@click.option(
    "--protocols",
    required=True,
    help="Protocol(s) supported by the client (comma separated).",
)
@click.option(
    "--country",
    default=None,
    help="Country, if it can't be resolved from the MSISDN.",
)
@click.option(
    "--operator",
    default=None,
    help="Operator name, if it can't be resolved from the MSISDN.",
)
@click.option(
    "--operator-code",
    default=None,
    help="PLMN (MCC+MNC) code, if it can't be resolved from the MSISDN.",
)
def create(msisdn, protocols, country, operator, operator_code):
    """Register a gateway client, resolving country/operator/PLMN from the MSISDN."""
    with session() as db:
        client = manager.create(
            db,
            msisdn,
            _split(protocols),
            country=country,
            operator=operator,
            operator_code=operator_code,
        )
        details = [
            (field, getattr(client, field))
            for field in ("msisdn", "country", "operator", "operator_code", "protocols")
        ]
    click.echo("Gateway client registered successfully.")
    click.echo("-" * 60)
    click.echo(f"{'Gateway Client Details':=^60}")
    for field, value in details:
        click.echo(f"{field.upper()}: {value}")


@cli.command()
@click.argument("msisdn", type=str, required=True)
def suggest(msisdn):
    """Show the details create would use for an MSISDN, and PLMN candidates."""
    try:
        suggestion = manager.suggest(manager.check_msisdn(msisdn))
    except manager.GatewayClientError as e:
        raise click.BadParameter(str(e)) from None
    for field in ("country", "iso", "country_code", "operator", "operator_code"):
        click.echo(f"{field.upper()}: {getattr(suggestion, field) or '-'}")
    click.echo(f"MATCH: {suggestion.match}")
    print_table(
        ["Operator Code", "Network"],
        [[c.operator_code, c.network] for c in suggestion.candidates],
        "No candidates.",
    )


@cli.command(name="list")
@click.option("--msisdn", type=str, help="Filter by MSISDN.")
@click.option("--country", type=str, help="Filter by country.")
@click.option("--operator", type=str, help="Filter by operator.")
def list_command(msisdn, country, operator):
    """List gateway clients, disabled ones included, optionally filtered."""
    with session() as db:
        clients = gateway_clients.find(
            db,
            msisdn=msisdn,
            country=country,
            operator=operator,
            include_disabled=True,
        )
    print_table(
        ["MSISDN", "Country", "Operator", "Operator Code", "Protocols", "Enabled"],
        [
            [
                c.msisdn,
                c.country,
                c.operator,
                c.operator_code,
                ",".join(c.protocols),
                "✓" if c.is_enabled else "-",
            ]
            for c in clients
        ],
        "No matching records found.",
    )


@cli.command()
@click.argument("msisdn", type=str, required=True)
@click.option("--country", type=str, help="New country value.")
@click.option("--operator", type=str, help="New operator value.")
@click.option("--operator-code", type=str, help="New PLMN (MCC+MNC) code.")
@click.option("--protocols", type=str, help="New protocol(s) value (comma separated).")
def update(msisdn, country, operator, operator_code, protocols):
    """Change a gateway client's details."""
    with session() as db:
        manager.update(
            db,
            manager.get_or_raise(db, msisdn),
            country=country,
            operator=operator,
            operator_code=operator_code,
            protocols=_split(protocols) if protocols else None,
        )
    click.echo("Gateway client updated successfully.")


@cli.command()
@click.argument("msisdn", type=str, required=True)
def enable(msisdn):
    """List a gateway client publicly again."""
    with session() as db:
        manager.set_enabled(db, manager.get_or_raise(db, msisdn), True)
    click.echo(f"Gateway client {msisdn} enabled.")


@cli.command()
@click.argument("msisdn", type=str, required=True)
def disable(msisdn):
    """Hide a gateway client from the public list without deleting it."""
    with session() as db:
        manager.set_enabled(db, manager.get_or_raise(db, msisdn), False)
    click.echo(f"Gateway client {msisdn} disabled.")


@cli.command()
@click.argument("msisdn", type=str, required=True)
def delete(msisdn):
    """Delete a gateway client."""
    with session() as db:
        manager.delete(db, manager.get_or_raise(db, msisdn))
    click.echo("Gateway client deleted successfully.")


@cli.command()
def countries():
    """List all unique countries with a registered gateway client."""
    with session() as db:
        clients = gateway_clients.find(db, include_disabled=True)
    for country in sorted({c.country for c in clients}):
        click.echo(country)


@cli.command()
@click.option("--country", required=True, help="Country to list operators for.")
def operators(country):
    """List all unique operators for a country."""
    with session() as db:
        clients = gateway_clients.find(db, country=country, include_disabled=True)
    for operator in sorted({c.operator for c in clients}):
        click.echo(operator)


@cli.group(name="mcc-mnc")
def mcc_mnc_group():
    """Inspect the MCC/MNC (PLMN) lookup data."""


@mcc_mnc_group.command(name="list")
@click.option("--country-code", type=str, help="Filter by country calling code.")
@click.option("--network", type=str, help="Filter by carrier name (substring).")
@click.option("--iso", type=str, help="Filter by ISO 3166-1 alpha-2 region.")
def mcc_mnc_list(country_code, network, iso):
    """Search the bundled MCC/MNC table."""
    matches = mcc_mnc.find_matches(country_code=country_code, network=network, iso=iso)
    headers = ["MCC", "MNC", "ISO", "Country", "Country Code", "Network"]
    rows = [
        [
            m["mcc"],
            m["mnc"],
            m["iso"],
            m["country"],
            m["country_code"],
            m["network"],
        ]
        for m in matches
    ]
    print_table(headers, rows, "No matching records found.")
