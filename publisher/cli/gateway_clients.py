# SPDX-License-Identifier: GPL-3.0-only

import click

from publisher.cli.output import print_table
from publisher.gateway_clients import mcc_mnc
from publisher.gateway_clients.manager import GatewayClientManager


@click.group()
@click.pass_context
def cli(ctx):
    """Manage the gateway client registry and MCC/MNC data."""
    ctx.obj = GatewayClientManager()


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
@click.pass_obj
def create(manager, msisdn, protocols, country, operator, operator_code):
    """Register a gateway client, resolving country/operator/PLMN from the MSISDN."""
    try:
        manifest = manager.create_client(
            msisdn,
            [p.strip() for p in protocols.split(",") if p.strip()],
            country=country,
            operator=operator,
            operator_code=operator_code,
        )
        click.echo("Gateway client registered successfully.")
        print("-" * 60)
        print(f"{'Gateway Client Details':=^60}")
        for field in ("msisdn", "country", "operator", "operator_code", "protocols"):
            print(f"{field.upper()}: {getattr(manifest, field)}")
    except ValueError as e:
        click.echo(f"Error: {e}", err=True)


@cli.command(name="list")
@click.option("--msisdn", type=str, help="Filter by MSISDN.")
@click.option("--country", type=str, help="Filter by country.")
@click.option("--operator", type=str, help="Filter by operator.")
@click.pass_obj
def list_command(manager, msisdn, country, operator):
    """List gateway clients, optionally filtered."""
    try:
        clients = manager.list_clients(
            msisdn=msisdn, country=country, operator=operator
        )
        headers = ["MSISDN", "Country", "Operator", "Operator Code", "Protocols"]
        rows = [
            [
                c.msisdn,
                c.country,
                c.operator,
                c.operator_code,
                ",".join(c.protocols),
            ]
            for c in clients
        ]
        print_table(headers, rows, "No matching records found.")
    except Exception as e:
        click.echo(f"Error listing gateway clients: {e}", err=True)


@cli.command()
@click.argument("msisdn", type=str, required=True)
@click.option("--country", type=str, help="New country value.")
@click.option("--operator", type=str, help="New operator value.")
@click.option("--operator-code", type=str, help="New PLMN (MCC+MNC) code.")
@click.option("--protocols", type=str, help="New protocol(s) value (comma separated).")
@click.pass_obj
def update(manager, msisdn, country, operator, operator_code, protocols):
    """Change a gateway client's details."""
    try:
        manager.update_client(
            msisdn,
            country=country,
            operator=operator,
            operator_code=operator_code,
            protocols=(
                [p.strip() for p in protocols.split(",") if p.strip()]
                if protocols
                else None
            ),
        )
        click.echo("Gateway client updated successfully.")
    except ValueError as e:
        click.echo(f"Error: {e}", err=True)


@cli.command()
@click.argument("msisdn", type=str, required=True)
@click.pass_obj
def delete(manager, msisdn):
    """Delete a gateway client."""
    try:
        manager.delete_client(msisdn)
        click.echo("Gateway client deleted successfully.")
    except ValueError as e:
        click.echo(f"Error: {e}", err=True)


@cli.command()
@click.pass_obj
def countries(manager):
    """List all unique countries with a registered gateway client."""
    for country in manager.list_countries():
        click.echo(country)


@cli.command()
@click.option("--country", required=True, help="Country to list operators for.")
@click.pass_obj
def operators(manager, country):
    """List all unique operators for a country."""
    for operator in manager.list_operators(country):
        click.echo(operator)


@cli.group(name="mcc-mnc")
def mcc_mnc_group():
    """Inspect and manage the MCC/MNC (PLMN) lookup data."""
    pass


@mcc_mnc_group.command(name="list")
@click.option("--country-code", type=str, help="Filter by country calling code.")
@click.option("--network", type=str, help="Filter by carrier name (substring).")
@click.option("--iso", type=str, help="Filter by ISO 3166-1 alpha-2 region.")
def mcc_mnc_list(country_code, network, iso):
    """List matching PLMN records from overrides + the vendored snapshot."""
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


@mcc_mnc_group.command(name="add-override")
@click.option("--mcc", required=True, help="Mobile Country Code.")
@click.option("--mnc", required=True, help="Mobile Network Code.")
@click.option("--country-code", required=True, help="Country calling code.")
@click.option("--network", required=True, help="Carrier name.")
@click.option("--country", required=True, help="Country name.")
@click.option("--iso", default=None, help="ISO 3166-1 alpha-2 country code.")
def mcc_mnc_add_override(mcc, mnc, country_code, network, country, iso):
    """Add or replace a PLMN override entry, keyed by (mcc, mnc)."""
    mcc_mnc.add_override(
        mcc=mcc,
        mnc=mnc,
        country_code=country_code,
        network=network,
        country=country,
        iso=iso,
    )
    click.echo(f"Override added for MCC={mcc} MNC={mnc}.")


@mcc_mnc_group.command(name="remove-override")
@click.option("--mcc", required=True, help="Mobile Country Code.")
@click.option("--mnc", required=True, help="Mobile Network Code.")
def mcc_mnc_remove_override(mcc, mnc):
    """Remove a PLMN override entry by (mcc, mnc)."""
    if mcc_mnc.remove_override(mcc, mnc):
        click.echo(f"Override removed for MCC={mcc} MNC={mnc}.")
    else:
        click.echo(f"No override found for MCC={mcc} MNC={mnc}.", err=True)
