# SPDX-License-Identifier: GPL-3.0-only
"""Configuration commands."""

import click

from publisher import config


@click.group()
def cli():
    """Inspect the configuration."""


@cli.command()
def check():
    """Check every configuration section and report all errors together."""
    errors = config.check()
    if errors:
        raise click.ClickException(str(config.ConfigError(errors)))
    click.echo("Configuration OK")
