"""
This program is free software: you can redistribute it under the terms
of the GNU General Public License, v. 3.0. If a copy of the GNU General
Public License was not distributed with this file, see <https://www.gnu.org/licenses/>.
"""

import click
from platforms.adapter_manager import AdapterManager


@click.group
def cli():
    """Platform CLI for managing adapters."""


@cli.command
@click.argument("github_url")
def add(github_url):
    """Add an adapter from a GitHub repository."""
    try:
        AdapterManager.add_adapter_from_github(github_url)
        click.echo(f"Adapter added successfully from {github_url}.")
    except Exception as e:
        click.echo(f"Error adding adapter: {e}")


@cli.command
@click.argument("adapter_name")
def remove(adapter_name):
    """Remove an adapter by its name."""
    try:
        AdapterManager.remove_adapter(adapter_name)
        click.echo(f"Adapter '{adapter_name}' removed successfully.")
    except ValueError as e:
        click.echo(f"Error: {e}")
    except Exception as e:
        click.echo(f"Unexpected error: {e}")


@cli.command
@click.argument("adapter_name", required=False)
@click.option("--install", is_flag=True, help="Reinstall dependencies after updating.")
def update(adapter_name, install):
    """Update adapters by pulling the latest changes."""
    try:
        AdapterManager.update_adapter(name=adapter_name, install=install)
        if adapter_name:
            click.echo(f"Adapter '{adapter_name}' updated successfully.")
        else:
            click.echo("All adapters updated successfully.")
    except ValueError as e:
        click.echo(f"Error: {e}")
    except Exception as e:
        click.echo(f"Unexpected error: {e}")


if __name__ == "__main__":
    cli()
