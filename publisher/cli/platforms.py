# SPDX-License-Identifier: GPL-3.0-only

import os
import subprocess
import sys
from pathlib import Path

import click

from publisher.cli.db import session
from publisher.cli.output import print_table
from publisher.models import platform_adapter as platform_adapters
from publisher.models.platform_adapter import PlatformAdapter
from publisher.platforms import manager
from relaysms_adapter_sdk.paths import CONFIG_DIR_ENV, STATE_DIR_ENV


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


def _version_options(command):
    command = click.option(
        "--branch",
        is_flag=True,
        help="Use the default branch, for repositories without version tags yet.",
    )(command)
    return click.option(
        "--tag", help="Version tag to install. Defaults to the newest."
    )(command)


def _check_version(tag, branch):
    if tag and branch:
        raise click.UsageError("Pass either --tag or --branch, not both.")


def _describe(adapter):
    return f"{adapter.tag or 'default branch'} ({adapter.commit[:12]})"


@cli.command()
@click.argument("github_url")
@_version_options
def add(github_url, tag, branch):
    """Add an adapter from a GitHub repository."""
    _check_version(tag, branch)
    with session() as db:
        adapter = manager.install(db, github_url, tag, branch=branch, log=[])
    manager.activate(adapter)
    click.echo(f"Adapter {adapter.name!r} added at {_describe(adapter)}.")


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
        adapter = _find_one(db, name, proto_id, cat_id)
        manager.remove(db, adapter, force=force)
    manager.delete_files(adapter)
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
        "Run a command an adapter installs, such as an admin script, from its "
        "virtualenv with its config and state directories.\n\n"
        "Put a '--' before the command so its arguments aren't confused with "
        "--proto-id/--cat-id.\n\n"
        "Example: publisher.sh platforms exec mastodon -- mastodon-register --help"
    ),
)
@click.argument("name")
@_filter_options
@click.argument("cli_args", nargs=-1, type=click.UNPROCESSED)
def exec_(name, proto_id, cat_id, cli_args):
    if not cli_args:
        raise click.UsageError("Name the command to run after '--'.")
    command, *args = cli_args
    with session() as db:
        adapter = _find_one(db, name, proto_id, cat_id)
    program = Path(adapter.venv_path).resolve() / "bin" / command
    if "/" in command or not program.is_file():
        raise click.ClickException(f"Adapter '{name}' has no command {command!r}.")

    env = {
        **os.environ,
        CONFIG_DIR_ENV: adapter.config_path,
        STATE_DIR_ENV: adapter.state_path,
    }
    result = subprocess.run([str(program), *args], cwd=adapter.path, env=env)
    sys.exit(result.returncode)


@cli.command()
@click.argument("name", required=False)
@_filter_options
@_version_options
def update(name, proto_id, cat_id, tag, branch):
    """Move one adapter, or all of them, to a new version."""
    _check_version(tag, branch)
    if tag and not name:
        raise click.UsageError("--tag needs an adapter name.")
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
                if adapter is None:
                    continue
                manager.update(db, adapter, tag, branch=branch, log=[])
            manager.activate(adapter)
            click.echo(f"Updated {adapter.name!r} to {_describe(adapter)}.")
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
            "Version",
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
                _describe(a),
            ]
            for a in adapters
        ],
        "No matching adapters found.",
    )


@cli.command(name="import")
def import_command():
    """Register adapter directories on disk and move their files out of the code."""
    with session() as db:
        imported = [adapter.name for adapter in manager.import_from_disk(db)]
        moved = [adapter.name for adapter in manager.move_files_out_of_code(db)]
    click.echo(f"Imported {len(imported)} adapter(s). {' '.join(imported)}".rstrip())
    if moved:
        click.echo(f"Moved the files of {len(moved)} adapter(s). {' '.join(moved)}")
