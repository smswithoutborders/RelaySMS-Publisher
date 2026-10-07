# SPDX-License-Identifier: GPL-3.0-only
"""Terminal output shared by the CLI commands."""

import click


def print_table(headers: list[str], rows: list[list], empty: str) -> None:
    """Print rows as a Markdown table, or `empty` when there are none."""
    if not rows:
        click.echo(empty)
        return

    widths = [
        max(len(str(row[i])) for row in [headers, *rows]) for i in range(len(headers))
    ]
    header = " | ".join(
        f"{name:<{width}}" for name, width in zip(headers, widths, strict=True)
    )
    separator = "-|-".join("-" * width for width in widths)
    click.echo(f"| {header} |")
    click.echo(f"| {separator} |")
    for row in rows:
        cells = " | ".join(
            f"{cell!s:<{width}}" for cell, width in zip(row, widths, strict=True)
        )
        click.echo(f"| {cells} |")
