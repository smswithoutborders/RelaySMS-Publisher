# SPDX-License-Identifier: GPL-3.0-only

import click

from publisher import credentials
from publisher.cli.db import session
from publisher.cli.output import print_table
from publisher.models import credential_session as credential_sessions
from publisher.models.credential import ALL_SCOPES, SCOPE_DESCRIPTIONS, Scope


def _format_time(value):
    return value.strftime("%Y-%m-%d %H:%M UTC") if value else "-"


def _format_scopes(credential):
    if credential.is_administrator:
        return "administrator"
    return ",".join(sorted(credential.scopes)) or "-"


def _show_password(username, password):
    click.echo(f"Username : {username}")
    click.echo(f"Password : {password}")
    click.echo(
        "Store this password now (e.g. in a password manager); "
        "it is not stored and can't be shown again.",
        err=True,
    )


def _username_option(help_text="Username of the credential."):
    return click.option("--username", required=True, help=help_text)


def _scope_options(command):
    command = click.option(
        "--administrator",
        is_flag=True,
        help="Grant every scope.",
    )(command)
    return click.option(
        "--scope",
        "scopes",
        multiple=True,
        type=click.Choice([scope.value for scope in Scope]),
        help="Scope to grant. Repeatable. See the scopes command.",
    )(command)


def _resolve_scopes(scopes, administrator):
    if administrator and scopes:
        raise click.UsageError("Pass either --scope or --administrator, not both.")
    if administrator:
        return ALL_SCOPES
    if not scopes:
        raise click.UsageError("Pass --scope at least once, or --administrator.")
    return scopes


@click.group()
def cli():
    """Manage credentials and their scopes."""


@cli.command(name="scopes")
def scopes_command():
    """List the available scopes."""
    print_table(
        ["SCOPE", "ALLOWS"],
        [[scope.value, SCOPE_DESCRIPTIONS[scope]] for scope in Scope],
        "No scopes defined.",
    )


@cli.command()
@_username_option("Username of the new credential.")
@_scope_options
def create(username, scopes, administrator):
    """Create a credential with a generated password."""
    with session() as db:
        credential, password = credentials.create(
            db, username, _resolve_scopes(scopes, administrator)
        )
        scope_text = _format_scopes(credential)

    click.echo(f"Credential created with scopes: {scope_text}")
    _show_password(credential.username, password)


@cli.command(name="list")
def list_command():
    """List credentials."""
    with session() as db:
        active_sessions = credential_sessions.count_active_by_credential(db)
        rows = [
            [
                credential.username,
                "yes" if credential.is_active else "no",
                _format_scopes(credential),
                _format_time(credential.created_at),
                _format_time(credential.last_login_at),
                active_sessions.get(credential.id, 0),
            ]
            for credential in credentials.list_credentials(db)
        ]

    print_table(
        ["USERNAME", "ACTIVE", "SCOPES", "CREATED", "LAST LOGIN", "SESSIONS"],
        rows,
        "No credentials found.",
    )


@cli.command(name="set-scopes")
@_username_option()
@_scope_options
def set_scopes(username, scopes, administrator):
    """Replace a credential's scopes. Takes effect on its next request."""
    with session() as db:
        credential = credentials.get_or_raise(db, username)
        credentials.update(
            db, credential, scopes=_resolve_scopes(scopes, administrator)
        )
        scope_text = _format_scopes(credential)

    click.echo(f"Scopes for {credential.username}: {scope_text}")


@cli.command(name="reset-password")
@_username_option()
def reset_password(username):
    """Generate a new password and end the credential's sessions."""
    with session() as db:
        credential = credentials.get_or_raise(db, username)
        password = credentials.reset_password(db, credential)

    click.echo("Password reset; existing sessions were ended.")
    _show_password(credential.username, password)


@cli.command()
@_username_option()
def disable(username):
    """Disable a credential and end its sessions."""
    with session() as db:
        credentials.update(db, credentials.get_or_raise(db, username), active=False)

    click.echo(f"Credential {username} disabled; existing sessions were ended.")


@cli.command()
@_username_option()
def enable(username):
    """Re-enable a disabled credential."""
    with session() as db:
        credentials.update(db, credentials.get_or_raise(db, username), active=True)

    click.echo(f"Credential {username} enabled.")


@cli.command()
@_username_option()
@click.confirmation_option(prompt="Permanently delete this credential?")
def delete(username):
    """Delete a credential and its sessions."""
    with session() as db:
        credentials.delete(db, credentials.get_or_raise(db, username))

    click.echo(f"Credential {username} deleted.")


@cli.command(name="revoke-sessions")
@_username_option()
def revoke_sessions(username):
    """Log a credential out of every web session."""
    with session() as db:
        revoked = credentials.revoke_sessions(
            db, credentials.get_or_raise(db, username)
        )

    click.echo(f"Ended {revoked} session(s) for {username}.")
