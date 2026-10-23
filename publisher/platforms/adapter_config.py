# SPDX-License-Identifier: GPL-3.0-only
"""An adapter's settings: the credentials.json in its config directory.

The adapter declares each setting in a [config] table of its adapter.toml, and
the inputs its setup method takes in [setup] tables.
"""

import logging
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
from publisher.platforms.manager import (
    AdapterError,
    AdapterFaultError,
    InvalidConfigError,
    flush,
)
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

logger = logging.getLogger(__name__)


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


def show(adapter: PlatformAdapter, declared: Manifest | None = None) -> list[Setting]:
    """Return each setting the adapter declares, without the secrets' values."""
    declared = declared or load_manifest(adapter)
    values = _read(adapter)
    return [
        Setting(
            field=field,
            value=None if field.secret else values.get(field.name),
            is_set=manifest.has_value(values.get(field.name)),
        )
        for field in declared.config
    ]


def missing(adapter: PlatformAdapter) -> list[str]:
    """Return the required settings that have no value."""
    return manifest.missing_values(load_manifest(adapter).config, _read(adapter))


def is_configured(adapter: PlatformAdapter) -> bool:
    """Whether every required setting has a value; False if its files are broken."""
    try:
        return not missing(adapter)
    except AdapterError as e:
        logger.warning("Can't read the settings of adapter %s: %s", adapter.id, e)
        return False


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
    settings = manifest.merge_values(_read(adapter), values)
    _save(session, adapter, settings, AuditAction.PLATFORMS_CONFIGURE, actor, values)


def setup(
    session: Session,
    adapter: PlatformAdapter,
    inputs: dict[str, Any],
    actor: Credential | None = None,
) -> None:
    """Run the adapter's setup and save the settings it returns, replacing the file.

    End the transaction that loaded adapter first, since the adapter call can be
    slow, and commit right after, as for update.

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
    # Updating the row bumps its version, so a concurrent change to the adapter
    # fails with a conflict.
    adapter.updated_at = utc_now()
    adapter.updated_by = actor.id if actor else None
    flush(session, adapter)
    audit_event.record(
        session, action, actor=actor, target=adapter, details={"keys": sorted(changed)}
    )
    # Written before the commit, unlike manager.activate: the flush locks the row
    # until the commit, so concurrent saves write the file one at a time.
    write_config(settings, directory=Path(adapter.config_path))
