# SPDX-License-Identifier: GPL-3.0-only
"""An adapter's settings: the credentials.json in its config directory.

The adapter declares each setting in a [config] table of its adapter.toml, and
the inputs its setup method takes in [setup] tables.
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from publisher.db.types import utc_now
from publisher.models import audit_event
from publisher.models.audit_event import AuditAction
from publisher.models.credential import Credential
from publisher.models.platform_adapter import PlatformAdapter
from publisher.platforms import ipc
from publisher.platforms.manager import AdapterError, flush
from relaysms_adapter_sdk import AdapterError as AdapterCallError
from relaysms_adapter_sdk import (
    AuthenticationError,
    InvalidParamsError,
    SetupRequest,
    manifest,
    read_config,
    write_config,
)
from relaysms_adapter_sdk.manifest import ConfigError, Field, Manifest, ManifestError


class InvalidConfigError(AdapterError):
    """Settings or setup inputs the caller gave don't fit the adapter."""


class AdapterFaultError(AdapterError):
    """The adapter or its files on this server are broken, not the caller's input."""


@dataclass(frozen=True)
class Setting:
    field: Field
    # None for a secret or an unset setting.
    value: Any
    is_set: bool


def load_manifest(adapter: PlatformAdapter) -> Manifest:
    try:
        return manifest.load(Path(adapter.path))
    except ManifestError as e:
        raise AdapterFaultError(str(e)) from e


def show(adapter: PlatformAdapter) -> list[Setting]:
    """Return each setting the adapter declares, without the secrets' values."""
    values = _read(adapter)
    return [
        Setting(
            field=field,
            value=None if field.secret else values.get(field.name),
            is_set=manifest.has_value(values.get(field.name)),
        )
        for field in load_manifest(adapter).config
    ]


def missing(adapter: PlatformAdapter) -> list[str]:
    """Return the required settings that have no value."""
    return manifest.missing_values(load_manifest(adapter).config, _read(adapter))


def update(
    session: Session,
    adapter: PlatformAdapter,
    values: dict[str, Any],
    actor: Credential | None = None,
) -> None:
    """Change the settings given and keep the others; None removes a setting.

    The file is replaced before this returns; commit right after.

    Raises:
        InvalidConfigError: A key isn't a setting, or a value has the wrong type.
    """
    values = _check(load_manifest(adapter).config, values, InvalidConfigError)
    settings = {**_read(adapter), **values}
    settings = {key: value for key, value in settings.items() if value is not None}
    _save(session, adapter, settings, AuditAction.PLATFORMS_CONFIGURE, actor, values)


def setup(
    session: Session,
    adapter: PlatformAdapter,
    inputs: dict[str, Any],
    actor: Credential | None = None,
) -> None:
    """Run the adapter's setup and save the settings it returns, replacing the file.

    Commit right after, as for update.

    Raises:
        InvalidConfigError: The inputs don't fit the adapter's [setup] tables, or
            the adapter rejected them.
        AdapterFaultError: The adapter's setup failed, or returned settings that
            don't fit its [config] tables.
        AdapterError: The adapter has no setup.
    """
    declared = load_manifest(adapter)
    if not declared.setup:
        raise AdapterError(f"{adapter.name} has no setup; set its config instead.")
    inputs = _check(declared.setup, inputs, InvalidConfigError, require_all=True)
    try:
        result = ipc.call(adapter, "setup", SetupRequest(inputs))
    except (InvalidParamsError, AuthenticationError) as e:
        raise InvalidConfigError(e.message) from e
    except AdapterCallError as e:
        raise AdapterFaultError(f"{adapter.name} setup failed: {e.message}") from e
    settings = _check(
        declared.config, result["settings"], AdapterFaultError, require_all=True
    )
    _save(session, adapter, settings, AuditAction.PLATFORMS_SETUP, actor, settings)


def _check(
    fields: tuple[Field, ...],
    values: dict[str, Any],
    error: type[AdapterError],
    *,
    require_all: bool = False,
) -> dict[str, Any]:
    try:
        return manifest.check_values(fields, values, require_all=require_all)
    except ConfigError as e:
        raise error(str(e)) from e


def _read(adapter: PlatformAdapter) -> dict[str, Any]:
    try:
        return read_config(directory=Path(adapter.config_path))
    except FileNotFoundError:
        return {}
    except ValueError as e:
        raise AdapterFaultError(str(e)) from e


def _save(
    session: Session,
    adapter: PlatformAdapter,
    settings: dict[str, Any],
    action: AuditAction,
    actor: Credential | None,
    changed: dict[str, Any],
) -> None:
    # Touching the row moves its version on, so a concurrent change conflicts.
    adapter.updated_at = utc_now()
    adapter.updated_by = actor.id if actor else None
    flush(session, adapter)
    audit_event.record(
        session, action, actor=actor, target=adapter, details={"keys": sorted(changed)}
    )
    # Written before the commit, unlike manager.activate: the flush holds the row,
    # so concurrent saves reach the file in order.
    write_config(settings, directory=Path(adapter.config_path))
