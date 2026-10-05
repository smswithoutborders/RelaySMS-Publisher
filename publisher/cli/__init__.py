# SPDX-License-Identifier: GPL-3.0-only
"""Command-line interface: python -m publisher GROUP COMMAND."""

import click

from publisher.cli import config, creds, gateway_clients, platforms, seed


@click.group()
def cli():
    """RelaySMS Publisher administration."""


cli.add_command(config.cli, name="config")
cli.add_command(creds.cli, name="creds")
cli.add_command(gateway_clients.cli, name="gateway-clients")
cli.add_command(platforms.cli, name="platforms")
cli.add_command(seed.cli, name="seed")
