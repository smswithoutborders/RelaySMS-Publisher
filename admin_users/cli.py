# SPDX-License-Identifier: GPL-3.0-only

from contextlib import contextmanager

import click

from db import get_session
from models import admin_session as admin_sessions
from models import admin_user as admin_users


@contextmanager
def _db():
    try:
        with get_session() as db:
            yield db
    except ValueError as e:
        raise click.ClickException(str(e))


def _print_table(headers, rows):
    if not rows:
        click.echo("No admin users found.")
        return

    widths = [
        max(len(str(row[i])) for row in [headers] + rows) for i in range(len(headers))
    ]

    header_str = " | ".join(f"{headers[i]:<{widths[i]}}" for i in range(len(headers)))
    sep_str = "-|-".join("-" * widths[i] for i in range(len(widths)))

    click.echo(f"| {header_str} |")
    click.echo(f"| {sep_str} |")
    for row in rows:
        row_str = " | ".join(f"{str(row[i]):<{widths[i]}}" for i in range(len(row)))
        click.echo(f"| {row_str} |")


def _format_time(value):
    return value.strftime("%Y-%m-%d %H:%M UTC") if value else "-"


def _show_password(email, password):
    click.echo(f"Email    : {email}")
    click.echo(f"Password : {password}")
    click.echo(
        "Store this password now (e.g. in a password manager); "
        "it is not stored and can't be shown again.",
        err=True,
    )


@click.group()
def cli():
    """Manage admin accounts."""


@cli.command()
@click.option("--email", required=True, help="Email address of the new admin.")
def create(email):
    """Create an admin with a generated password."""
    with _db() as db:
        admin, password = admin_users.create_admin(db, email)

    click.echo("Admin user created successfully.")
    _show_password(admin.email, password)


@cli.command(name="list")
def list_command():
    """List admin users."""
    with _db() as db:
        active_sessions = admin_sessions.count_active_by_admin(db)
        rows = [
            [
                admin.email,
                "yes" if admin.is_active else "no",
                _format_time(admin.created_at),
                _format_time(admin.last_login_at),
                active_sessions.get(admin.id, 0),
            ]
            for admin in admin_users.list_admins(db)
        ]

    _print_table(["EMAIL", "ACTIVE", "CREATED", "LAST LOGIN", "SESSIONS"], rows)


@cli.command(name="reset-password")
@click.option("--email", required=True, help="Email address of the admin.")
def reset_password(email):
    """Generate a new password and end the admin's sessions."""
    with _db() as db:
        admin, password = admin_users.reset_password(db, email)

    click.echo("Password reset; existing sessions were ended.")
    _show_password(admin.email, password)


@cli.command()
@click.option("--email", required=True, help="Email address of the admin.")
def disable(email):
    """Disable an admin and end their sessions."""
    with _db() as db:
        admin_users.set_active(db, email, False)

    click.echo(f"Admin user {email} disabled; existing sessions were ended.")


@cli.command()
@click.option("--email", required=True, help="Email address of the admin.")
def enable(email):
    """Re-enable a disabled admin."""
    with _db() as db:
        admin_users.set_active(db, email, True)

    click.echo(f"Admin user {email} enabled.")


@cli.command()
@click.option("--email", required=True, help="Email address of the admin.")
@click.confirmation_option(prompt="Permanently delete this admin user?")
def delete(email):
    """Delete an admin and their sessions."""
    with _db() as db:
        admin_users.delete_admin(db, email)

    click.echo(f"Admin user {email} deleted.")


@cli.command(name="revoke-sessions")
@click.option("--email", required=True, help="Email address of the admin.")
def revoke_sessions(email):
    """Log an admin out of every web session."""
    with _db() as db:
        revoked = admin_sessions.revoke_all(db, admin_users.get_or_raise(db, email).id)

    click.echo(f"Ended {revoked} session(s) for {email}.")


if __name__ == "__main__":
    cli()
