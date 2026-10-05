# SPDX-License-Identifier: GPL-3.0-only
"""Credentials: validation, passwords, permission checks and changes."""

import contextlib
import re
import secrets
from collections.abc import Iterable
from functools import lru_cache
from typing import cast

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from sqlalchemy import CursorResult, select
from sqlalchemy import update as sql_update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import set_committed_value

from publisher.db.types import utc_now
from publisher.errors import PublisherError
from publisher.models.credential import (
    ALL_SCOPES,
    MAX_USERNAME_LENGTH,
    Credential,
    CredentialScope,
    Scope,
)
from publisher.models.credential_session import revoke_all

_USERNAME_PATTERN = re.compile(rf"^[a-z0-9][a-z0-9._-]{{2,{MAX_USERNAME_LENGTH - 1}}}$")

password_hasher = PasswordHasher()

# Each scope here can only be granted with the scope it maps to.
_REQUIRES = {
    Scope.STATS_PUBLICATIONS_REASONS: Scope.STATS_PUBLICATIONS_READ,
    Scope.GC_WRITE: Scope.GC_READ,
    Scope.PLATFORMS_WRITE: Scope.PLATFORMS_READ,
    Scope.CREDS_WRITE: Scope.CREDS_READ,
}


class CredentialError(PublisherError):
    pass


class InvalidCredentialError(CredentialError):
    pass


class CredentialExistsError(CredentialError):
    pass


class CredentialNotFoundError(CredentialError):
    pass


class CredentialPermissionError(CredentialError):
    pass


class CredentialConflictError(CredentialError):
    pass


def _normalize_username(username: str) -> str:
    normalized = username.strip().lower()
    if not _USERNAME_PATTERN.match(normalized):
        raise InvalidCredentialError(
            f"Invalid username {username!r}: use 3-32 of a-z, 0-9, '.', '_' or '-', "
            "starting with a letter or digit"
        )
    return normalized


def parse_scopes(values: Iterable[str]) -> frozenset[Scope]:
    scopes = set()
    for value in values:
        if value not in ALL_SCOPES:
            raise InvalidCredentialError(f"Unknown scope {value!r}")
        scopes.add(Scope(value))
    for scope in scopes:
        required = _REQUIRES.get(scope)
        if required and required not in scopes:
            raise InvalidCredentialError(f"Scope {scope} requires {required}")
    return frozenset(scopes)


def _set_scope_rows(credential: Credential, scopes: frozenset[Scope]) -> None:
    credential.scope_rows = [
        row for row in credential.scope_rows if row.scope in scopes
    ] + [
        CredentialScope(scope=scope.value)
        for scope in sorted(scopes - credential.scopes)
    ]


def _generate_password() -> str:
    return secrets.token_urlsafe(24)


@lru_cache(maxsize=1)
def _dummy_hash() -> str:
    return password_hasher.hash(_generate_password())


def _claim(session: Session, credential: Credential) -> None:
    """Bump the version, failing if the credential changed since it was read."""
    result = cast(
        CursorResult,
        session.execute(
            sql_update(Credential)
            .where(
                Credential.id == credential.id, Credential.version == credential.version
            )
            .values(version=Credential.version + 1)
            .execution_options(synchronize_session=False)
        ),
    )
    if result.rowcount != 1:
        raise CredentialConflictError(
            f"Credential {credential.username!r} was changed concurrently; retry"
        )
    set_committed_value(credential, "version", credential.version + 1)


def _end_sessions(session: Session, credential: Credential) -> int:
    session.execute(
        sql_update(Credential)
        .where(Credential.id == credential.id)
        .values(session_version=Credential.session_version + 1)
        .execution_options(synchronize_session=False)
    )
    set_committed_value(credential, "session_version", credential.session_version + 1)
    return revoke_all(session, credential.id)


def _authorize_change(
    session: Session,
    actor: Credential | None,
    target: Credential | None,
    scopes: Iterable[Scope] = (),
) -> None:
    # No actor means the CLI, which is trusted.
    if actor is not None:
        check_can_manage(actor, target, scopes)
        # Fails if the actor itself changed after it was authenticated.
        _claim(session, actor)
    if target is not None:
        _claim(session, target)


def get_by_username(session: Session, username: str) -> Credential | None:
    return session.scalars(
        select(Credential).filter_by(username=username.strip().lower())
    ).first()


def get_or_raise(session: Session, username: str) -> Credential:
    credential = get_by_username(session, username)
    if credential is None:
        raise CredentialNotFoundError(f"No credential with username {username!r}")
    return credential


def list_credentials(session: Session) -> list[Credential]:
    return list(session.scalars(select(Credential).order_by(Credential.username)))


def check_can_manage(
    actor: Credential,
    target: Credential | None = None,
    scopes: Iterable[Scope] = (),
) -> None:
    """Check that actor may change target and grant scopes.

    Raises:
        CredentialPermissionError: When the change goes beyond the actor's scopes.
    """
    if Scope.CREDS_WRITE not in actor.scopes:
        raise CredentialPermissionError(f"Requires scope {Scope.CREDS_WRITE}")
    if target is not None:
        if target.id == actor.id:
            raise CredentialPermissionError("A credential can't change itself")
        if not target.scopes <= actor.scopes:
            raise CredentialPermissionError(
                "Can't change a credential with scopes you don't hold"
            )
    missing = set(scopes) - actor.scopes
    if missing:
        raise CredentialPermissionError(
            f"Can't grant scopes you don't hold: {', '.join(sorted(missing))}"
        )


def create(
    session: Session,
    username: str,
    scopes: Iterable[str],
    actor: Credential | None = None,
) -> tuple[Credential, str]:
    username = _normalize_username(username)
    scopes = parse_scopes(scopes)
    _authorize_change(session, actor, None, scopes)

    password = _generate_password()
    credential = Credential(
        username=username, password_hash=password_hasher.hash(password)
    )
    _set_scope_rows(credential, scopes)
    session.add(credential)
    try:
        session.flush()
    except IntegrityError:
        raise CredentialExistsError(f"Credential {username!r} already exists") from None
    return credential, password


def update(
    session: Session,
    credential: Credential,
    *,
    scopes: Iterable[str] | None = None,
    active: bool | None = None,
    actor: Credential | None = None,
) -> None:
    new_scopes = parse_scopes(scopes) if scopes is not None else None
    _authorize_change(session, actor, credential, new_scopes or ())
    if new_scopes is not None:
        _set_scope_rows(credential, new_scopes)
    if active is not None:
        credential.is_active = active
        if not active:
            _end_sessions(session, credential)
    session.flush()


def reset_password(
    session: Session, credential: Credential, actor: Credential | None = None
) -> str:
    _authorize_change(session, actor, credential)
    password = _generate_password()
    credential.password_hash = password_hasher.hash(password)
    _end_sessions(session, credential)
    return password


def revoke_sessions(
    session: Session, credential: Credential, actor: Credential | None = None
) -> int:
    _authorize_change(session, actor, credential)
    return _end_sessions(session, credential)


def delete(
    session: Session, credential: Credential, actor: Credential | None = None
) -> None:
    _authorize_change(session, actor, credential)
    session.delete(credential)
    session.flush()


def authenticate(session: Session, username: str, password: str) -> Credential | None:
    credential = get_by_username(session, username)
    if credential is None:
        # Hash anyway so response timing doesn't reveal which usernames exist.
        with contextlib.suppress(VerificationError):
            password_hasher.verify(_dummy_hash(), password)
        return None

    try:
        password_hasher.verify(credential.password_hash, password)
    except VerificationError, InvalidHashError:
        return None

    if not credential.is_active:
        return None

    if password_hasher.check_needs_rehash(credential.password_hash):
        # Upgrades the hash only if it's still the one just verified.
        session.execute(
            sql_update(Credential)
            .where(
                Credential.id == credential.id,
                Credential.password_hash == credential.password_hash,
            )
            .values(password_hash=password_hasher.hash(password))
            .execution_options(synchronize_session=False)
        )
    return credential


def record_login(
    session: Session, credential: Credential, *, min_interval_seconds: int = 0
) -> None:
    now = utc_now()
    last = credential.last_login_at
    if last is None or (now - last).total_seconds() >= min_interval_seconds:
        session.execute(
            sql_update(Credential)
            .where(Credential.id == credential.id)
            .values(last_login_at=now)
            .execution_options(synchronize_session=False)
        )
        set_committed_value(credential, "last_login_at", now)
