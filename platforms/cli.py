"""
This program is free software: you can redistribute it under the terms
of the GNU General Public License, v. 3.0. If a copy of the GNU General
Public License was not distributed with this file, see <https://www.gnu.org/licenses/>.
"""

import click
from platforms.adapter_manager import AdapterManager


@click.group()
def cli():
    """Platform CLI for managing adapters."""
    pass


@cli.command()
@click.argument("github_url")
def add(github_url):
    """
    Add an adapter from a GitHub repository.

    Args:
        github_url (str): The GitHub URL of the repository to clone.
    """
    try:
        AdapterManager.add_adapter_from_github(github_url)
    except Exception as e:
        click.echo(f"Error adding adapter: {e}")


if __name__ == "__main__":
    cli()
