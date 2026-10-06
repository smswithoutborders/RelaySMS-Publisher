# SPDX-License-Identifier: GPL-3.0-only

import subprocess
import sys
from pathlib import Path

import click

from publisher.cli.db import session
from publisher.cli.output import print_table
from publisher.models import platform_adapter as platform_adapters
from publisher.models.platform_adapter import PlatformAdapter
from publisher.platforms import manager


def _filter_options(command):
    command = click.option(
        "--cat-id", type=int, help="Filter target adapter by category ID."
    )(command)
    return click.option(
        "--proto-id", type=int, help="Filter target adapter by protocol ID."
    )(command)


def _find_one(db, name, proto_id, cat_id):
    matched = platform_adapters.find(
        db, name=name, proto_id=proto_id, cat_id=cat_id, include_disabled=True
    )
    if not matched:
        raise click.BadParameter("No registered adapter found matching criteria.")
    if len(matched) > 1:
        raise click.UsageError(
            "Multiple matches found. Add filters using --proto-id or --cat-id."
        )
    return matched[0]


@click.group()
def cli():
    """Manage platform adapters."""


@cli.command()
@click.argument("github_url")
def add(github_url):
    """Add an adapter from a GitHub repository."""
    with session() as db:
        adapter = manager.add_from_github(db, github_url)
        click.echo(f"Adapter {adapter.name!r} added from {github_url}.")


@cli.command()
@click.argument("name")
@_filter_options
@click.option(
    "--force",
    is_flag=True,
    help="Remove even with linked accounts, whose tokens then can't be revoked.",
)
def remove(name, proto_id, cat_id, force):
    """Remove an adapter, matched by name and optional IDs."""
    with session() as db:
        manager.remove(db, _find_one(db, name, proto_id, cat_id), force=force)
    click.echo(f"Adapter {name!r} removed.")


@cli.command()
@click.argument("name")
@_filter_options
def enable(name, proto_id, cat_id):
    """Offer an adapter to users again."""
    with session() as db:
        manager.set_enabled(db, _find_one(db, name, proto_id, cat_id), True)
    click.echo(f"Adapter {name!r} enabled.")


@cli.command()
@click.argument("name")
@_filter_options
def disable(name, proto_id, cat_id):
    """Hide an adapter from users; it can still revoke tokens."""
    with session() as db:
        manager.set_enabled(db, _find_one(db, name, proto_id, cat_id), False)
    click.echo(f"Adapter {name!r} disabled.")


@cli.command(
    name="exec",
    help=(
        "Run an adapter's own admin CLI (its cli.py) inside its own "
        "virtualenv.\n\n"
        "Put a '--' before the adapter's own arguments so they aren't "
        "confused with --proto-id/--cat-id.\n\n"
        "Example: publisher.sh platforms exec mastodon -- register -i"
    ),
)
@click.argument("name")
@_filter_options
@click.argument("cli_args", nargs=-1, type=click.UNPROCESSED)
def exec_(name, proto_id, cat_id, cli_args):
    with session() as db:
        adapter = _find_one(db, name, proto_id, cat_id)
    adapter_path = Path(adapter.path).resolve()
    adapter_cli = adapter_path / "cli.py"
    python_exec = Path(adapter.venv_path).resolve() / "bin" / "python3"

    if not adapter_cli.is_file():
        raise click.ClickException(f"Adapter '{name}' has no cli.py: nothing to run.")
    if not python_exec.is_file():
        raise click.ClickException(
            f"Adapter '{name}' virtualenv not found at {python_exec.parent.parent}."
        )

    result = subprocess.run(
        [str(python_exec), str(adapter_cli), *cli_args], cwd=adapter_path
    )
    sys.exit(result.returncode)


@cli.command()
@click.argument("name", required=False)
@_filter_options
@click.option("--install", is_flag=True, help="Reinstall dependencies after updating.")
def update(name, proto_id, cat_id, install):
    """Pull the latest changes for one adapter, or all of them."""
    with session() as db:
        if name or proto_id is not None or cat_id is not None:
            adapters = [_find_one(db, name, proto_id, cat_id)]
        else:
            adapters = platform_adapters.find(db, include_disabled=True)
        ids = [adapter.id for adapter in adapters]

    failed = False
    # One transaction each, so one bad adapter doesn't undo the others.
    for adapter_id in ids:
        try:
            with session() as db:
                adapter = db.get(PlatformAdapter, adapter_id)
                if adapter is not None:
                    manager.update(db, adapter, install=install)
                    click.echo(f"Updated {adapter.name!r} to {adapter.commit}.")
        except click.ClickException as e:
            failed = True
            click.echo(f"Error updating adapter {adapter_id}: {e.message}", err=True)
    if failed:
        sys.exit(1)


@cli.command(name="list")
@click.option("--name", help="Filter by adapter name.")
@click.option("--proto-id", type=int, help="Filter by protocol ID.")
@click.option("--cat-id", type=int, help="Filter by category ID.")
def list_command(name, proto_id, cat_id):
    """List adapters, optionally filtered."""
    with session() as db:
        adapters = platform_adapters.find(
            db, name=name, proto_id=proto_id, cat_id=cat_id, include_disabled=True
        )

    print_table(
        [
            "ID",
            "Name",
            "Display Name",
            "Protocol ID",
            "Category ID",
            "Auth Provider",
            "Offline",
            "Enabled",
            "Commit",
        ],
        [
            [
                a.id,
                a.name,
                a.display_name,
                str(a.proto_id),
                str(a.cat_id),
                a.auth_provider or "-",
                "✓" if a.supports_offline_first else "-",
                "✓" if a.is_enabled else "-",
                a.commit[:12],
            ]
            for a in adapters
        ],
        "No matching adapters found.",
    )


@cli.command(name="import")
def import_command():
    """Register adapter directories on disk that aren't registered yet."""
    with session() as db:
        imported = manager.import_from_disk(db)
        names = [adapter.name for adapter in imported]
    click.echo(f"Imported {len(names)} adapter(s). {' '.join(names)}".rstrip())
