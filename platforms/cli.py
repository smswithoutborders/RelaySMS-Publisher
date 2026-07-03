# SPDX-License-Identifier: GPL-3.0-only

import click

from platforms.adapter_manager import AdapterManager

manager = AdapterManager()


@click.group()
def cli():
    """Platform CLI for managing adapters."""
    pass


@cli.command()
@click.argument("github_url")
def add(github_url):
    """Add an adapter from a GitHub repository."""
    try:
        manager.add_adapter_from_github(github_url)
        click.echo(f"Adapter added successfully from {github_url}.")
    except Exception as e:
        click.echo(f"Error adding adapter: {e}", err=True)


@cli.command()
@click.argument("name", type=str, required=True)
@click.option("--proto-id", type=int, help="Filter target adapter by protocol ID.")
@click.option("--cat-id", type=int, help="Filter target adapter by category ID.")
def remove(name, proto_id, cat_id):
    """Remove an adapter by its platform fields."""
    try:
        matched_ids = manager.find_adapter_ids(
            name=name, proto_id=proto_id, cat_id=cat_id
        )

        if not matched_ids:
            raise click.BadParameter("No registered adapter found matching criteria.")
        if len(matched_ids) > 1:
            raise click.UsageError(
                "Multiple matches found. Add filters using --proto-id or --cat-id."
            )

        manager.remove_adapter(matched_ids[0])
        click.echo(f"Adapter '{name}' removed successfully.")
    except Exception as e:
        click.echo(f"Error: {e}", err=True)


@cli.command()
@click.argument("name", type=str, required=False)
@click.option("--proto-id", type=int, help="Filter target adapter by protocol ID.")
@click.option("--cat-id", type=int, help="Filter target adapter by category ID.")
@click.option("--install", is_flag=True, help="Reinstall dependencies after updating.")
def update(name, proto_id, cat_id, install):
    """Update specific or all adapters by pulling latest changes."""
    try:
        if name or proto_id or cat_id:
            matched_ids = manager.find_adapter_ids(
                name=name, proto_id=proto_id, cat_id=cat_id
            )

            if not matched_ids:
                raise click.BadParameter("No adapter found matching criteria.")
            if len(matched_ids) > 1:
                raise click.UsageError(
                    "Multiple matches found. Clarify target using --proto-id or --cat-id."
                )

            manager.update_adapter(adapter_id=matched_ids[0], install=install)
            click.echo("Adapter updated successfully.")
        else:
            manager.update_adapter(install=install)
            click.echo("All adapters updated successfully.")

    except Exception as e:
        click.echo(f"Error: {e}", err=True)


@cli.command(name="list")
@click.option("--name", type=str, help="Filter by adapter name.")
@click.option("--proto-id", type=int, help="Filter by protocol ID.")
@click.option("--cat-id", type=int, help="Filter by category ID string.")
def list_command(name, proto_id, cat_id):
    """List adapters matching criteria in Markdown table format."""
    try:
        adapters = manager.list_adapters(name=name, proto_id=proto_id, cat_id=cat_id)

        if not adapters:
            click.echo("No matching adapters found.")
            return

        headers = [
            "ID",
            "Name",
            "Display Name",
            "Protocol ID",
            "Category ID",
            "Auth Provider",
        ]
        rows = [
            [
                str(a.id),
                str(a.name),
                str(a.display_name),
                str(a.proto_id),
                str(a.cat_id),
                str(a.auth_provider) if a.auth_provider else "-",
            ]
            for a in adapters
        ]

        widths = [
            max(len(str(row[i])) for row in [headers] + rows)
            for i in range(len(headers))
        ]

        header_str = " | ".join(
            f"{headers[i]:<{widths[i]}}" for i in range(len(headers))
        )
        sep_str = "-|-".join("-" * widths[i] for i in range(len(widths)))

        click.echo(f"| {header_str} |")
        click.echo(f"| {sep_str} |")
        for row in rows:
            row_str = " | ".join(f"{row[i]:<{widths[i]}}" for i in range(len(row)))
            click.echo(f"| {row_str} |")

    except Exception as e:
        click.echo(f"Error listing adapters: {e}", err=True)


@cli.command()
@click.confirmation_option(
    prompt="This will overwrite the current registry with data from disk. Continue?"
)
def recover():
    """Recover registry from existing adapter directories on disk."""
    try:
        manager.recover_registry()
    except Exception as e:
        click.echo(f"Error during recovery: {e}", err=True)


if __name__ == "__main__":
    cli()
