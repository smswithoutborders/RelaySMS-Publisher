# SPDX-License-Identifier: GPL-3.0-only

import click

from gateway_clients import mcc_mnc
from gateway_clients.gateway_client_manager import GatewayClientManager

manager = GatewayClientManager()


def _print_table(headers, rows):
    if not rows:
        click.echo("No matching records found.")
        return

    widths = [
        max(len(str(row[i])) for row in [headers] + rows) for i in range(len(headers))
    ]

    header_str = " | ".join(f"{headers[i]:<{widths[i]}}" for i in range(len(headers)))
    sep_str = "-|-".join("-" * widths[i] for i in range(len(widths)))

    click.echo(f"| {header_str} |")
    click.echo(f"| {sep_str} |")
    for row in rows:
        row_str = " | ".join(f"{row[i]:<{widths[i]}}" for i in range(len(row)))
        click.echo(f"| {row_str} |")


@click.group()
def cli():
    """Gateway Clients CLI for managing the registry of gateway-client phone numbers."""
    pass


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
    """Register a new gateway client, resolving country/operator/PLMN from the MSISDN."""
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
def list_command(msisdn, country, operator):
    """List gateway clients matching criteria in Markdown table format."""
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
        _print_table(headers, rows)
    except Exception as e:
        click.echo(f"Error listing gateway clients: {e}", err=True)


@cli.command()
@click.argument("msisdn", type=str, required=True)
@click.option("--country", type=str, help="New country value.")
@click.option("--operator", type=str, help="New operator value.")
@click.option("--operator-code", type=str, help="New PLMN (MCC+MNC) code.")
@click.option("--protocols", type=str, help="New protocol(s) value (comma separated).")
def update(msisdn, country, operator, operator_code, protocols):
    """Update an existing gateway client."""
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
def delete(msisdn):
    """Delete an existing gateway client."""
    try:
        manager.delete_client(msisdn)
        click.echo("Gateway client deleted successfully.")
    except ValueError as e:
        click.echo(f"Error: {e}", err=True)


@cli.command()
def countries():
    """List all unique countries with a registered gateway client."""
    for country in manager.list_countries():
        click.echo(country)


@cli.command()
@click.option("--country", required=True, help="Country to list operators for.")
def operators(country):
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
    _print_table(headers, rows)


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


if __name__ == "__main__":
    cli()
