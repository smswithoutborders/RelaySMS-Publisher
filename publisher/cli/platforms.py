# SPDX-License-Identifier: GPL-3.0-only

import subprocess
import sys
from pathlib import Path

import click

from publisher.cli.db import session
from publisher.cli.output import print_table
from publisher.models import platform_adapter as platform_adapters
from publisher.models.platform_adapter import PlatformAdapter
from publisher.platforms import adapter_config, ipc, manager
from relaysms_adapter_sdk import manifest
from relaysms_adapter_sdk.manifest import ConfigError, Field, FieldType


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


_tag_option = click.option(
    "--tag", help="Version tag to install. Defaults to the newest."
)


def _describe(adapter):
    return f"{adapter.tag or 'untagged'} ({adapter.commit[:12]})"


@cli.command()
@click.argument("github_url")
@_tag_option
def add(github_url, tag):
    """Add an adapter from a GitHub repository."""
    with session() as db:
        adapter = manager.install(db, github_url, tag, log=[])
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

    result = subprocess.run(
        [str(program), *args], cwd=adapter.path, env=ipc.adapter_env(adapter)
    )
    sys.exit(result.returncode)


@cli.command()
@click.argument("name", required=False)
@_filter_options
@_tag_option
def update(name, proto_id, cat_id, tag):
    """Move one adapter, or all of them, to a new version."""
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
                manager.update(db, adapter, tag, log=[])
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
            "Configured",
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
                "✓" if adapter_config.is_configured(a) else "-",
                _describe(a),
            ]
            for a in adapters
        ],
        "No matching adapters found.",
    )


@cli.group(name="config")
def config_group():
    """Show and change an adapter's settings, the credentials.json it reads."""


@config_group.command(name="show")
@click.argument("name")
@_filter_options
def config_show(name, proto_id, cat_id):
    """Show an adapter's settings; secrets only show whether they're set."""
    with session() as db:
        adapter = _find_one(db, name, proto_id, cat_id)
        settings = adapter_config.show(adapter)

    print_table(
        ["Setting", "Value", "Required", "Description"],
        [
            [
                s.field.name,
                _shown_value(s),
                "✓" if s.field.required else "-",
                s.field.description or "",
            ]
            for s in settings
        ],
        f"Adapter {name!r} declares no settings.",
    )


@config_group.command(name="set")
@click.argument("name")
@click.argument("values", nargs=-1, metavar="[KEY=VALUE|KEY]...")
@click.option("--unset", multiple=True, metavar="KEY", help="Remove a setting.")
@_filter_options
def config_set(name, values, unset, proto_id, cat_id):
    """Change some settings and keep the rest.

    Give a bare KEY to be asked for its value. Lists are comma-separated.
    """
    if not values and not unset:
        raise click.UsageError("Give a setting to change, or --unset one.")
    adapter = _adapter(name, proto_id, cat_id)
    changes = _values(adapter_config.load_manifest(adapter).config, values)
    changes |= dict.fromkeys(unset)
    with session() as db:
        adapter_config.update(db, _current(db, adapter), changes)
    click.echo(f"Saved the settings of {name!r}.")


@cli.command()
@click.argument("name")
@click.option(
    "--input",
    "inputs",
    multiple=True,
    metavar="KEY=VALUE",
    help="Repeatable; KEY=@PATH for a file. Asks for required inputs not given.",
)
@_filter_options
def setup(name, inputs, proto_id, cat_id):
    """Run an adapter's setup, such as registering an app, and save its settings."""
    adapter = _adapter(name, proto_id, cat_id)
    fields = adapter_config.load_manifest(adapter).setup
    given = {text.partition("=")[0].lower() for text in inputs}
    unanswered = [f.name for f in fields if f.required and f.name not in given]
    values = _values(fields, [*inputs, *unanswered])
    with session() as db:
        current = _current(db, adapter)
        db.commit()
        adapter_config.setup(db, current, values)
    click.echo(f"Saved the settings of {name!r}.")


def _adapter(name, proto_id, cat_id) -> PlatformAdapter:
    with session() as db:
        return _find_one(db, name, proto_id, cat_id)


def _current(db, adapter: PlatformAdapter) -> PlatformAdapter:
    current = db.get(PlatformAdapter, adapter.id)
    if current is None:
        raise click.ClickException(f"Adapter {adapter.name!r} was removed.")
    return current


def _values(fields: tuple[Field, ...], texts) -> dict:
    """Read KEY=VALUE texts, asking for the value of each bare KEY."""
    by_name = {field.name: field for field in fields}
    asked = []
    for key in (text for text in texts if "=" not in text):
        if key.lower() not in by_name:
            raise click.ClickException(f"{key} isn't a setting of this adapter.")
        asked.append(by_name[key.lower()])
    try:
        values = manifest.parse_inputs(fields, [t for t in texts if "=" in t])
        return values | manifest.ask_values(asked, _ask)
    except ConfigError as e:
        raise click.ClickException(str(e)) from e


def _ask(field: Field) -> str:
    question = field.description or field.name
    if field.type is FieldType.FILE:
        return click.prompt(f"{question} (path)")
    return click.prompt(question, hide_input=field.secret)


def _shown_value(setting: adapter_config.Setting) -> str:
    if setting.field.secret:
        return "(secret, set)" if setting.is_set else "(secret, not set)"
    if not setting.is_set:
        return "-"
    value = setting.value
    return ", ".join(value) if isinstance(value, list) else str(value)


@cli.command(name="import")
def import_command():
    """Register adapter directories on disk and move their files out of the code."""
    with session() as db:
        imported = [adapter.name for adapter in manager.import_from_disk(db)]
        moved = [adapter.name for adapter in manager.move_files_out_of_code(db)]
    click.echo(f"Imported {len(imported)} adapter(s). {' '.join(imported)}".rstrip())
    if moved:
        click.echo(f"Moved the files of {len(moved)} adapter(s). {' '.join(moved)}")
