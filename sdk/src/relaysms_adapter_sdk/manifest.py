# SPDX-License-Identifier: GPL-3.0-only
"""Reads adapter.toml, which describes an adapter to the Publisher."""

import re
import tomllib
from collections.abc import Iterable
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any

from relaysms_adapter_sdk.paths import lowercase_keys

FILENAME = "adapter.toml"

_ENTRY_RE = re.compile(r"^[A-Za-z_][\w.]*:[A-Za-z_]\w*$")
_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9_-]*$")
_KEY_RE = re.compile(r"^[a-z][a-z0-9_]*$")


class Protocol(StrEnum):
    OAUTH2 = "oauth2"
    PNBA = "pnba"


class Category(StrEnum):
    EMAIL = "email"
    MESSAGE = "message"
    TEXT = "text"
    BRIDGE = "bridge"


class FieldType(StrEnum):
    STRING = "string"
    INTEGER = "integer"
    BOOLEAN = "boolean"
    LIST = "list"


class ManifestError(ValueError):
    pass


class ConfigError(ValueError):
    pass


@dataclass(frozen=True)
class Field:
    """A key in credentials.json, declared in a [config] table."""

    name: str
    type: FieldType = FieldType.STRING
    required: bool = False
    # Write-only: the Publisher never shows its value.
    secret: bool = False
    description: str | None = None


@dataclass(frozen=True)
class Manifest:
    entry: str
    name: str
    display_name: str
    protocol: Protocol
    category: Category
    offline_first: bool = False
    auth_provider: str | None = None
    icon_svg: str | None = None
    icon_png: str | None = None
    config: tuple[Field, ...] = ()


def load(directory: Path) -> Manifest:
    """Read the manifest in an adapter's directory.

    Raises:
        ManifestError: The file is missing or invalid.
    """
    path = directory / FILENAME
    try:
        return parse(path.read_text(encoding="utf-8"))
    except OSError as e:
        raise ManifestError(f"Can't read {path}: {e.strerror}") from e


def parse(text: str) -> Manifest:
    """Parse a manifest's TOML.

    Raises:
        ManifestError: The TOML or one of its fields is invalid.
    """
    try:
        data = tomllib.loads(text)
    except tomllib.TOMLDecodeError as e:
        raise ManifestError(f"Invalid TOML: {e}") from e

    entry = _str(data, "entry")
    if not _ENTRY_RE.match(entry):
        raise ManifestError(f"entry must look like package.module:Class, not {entry!r}")
    name = _str(data, "name")
    if not _NAME_RE.match(name):
        raise ManifestError(f"name must be lowercase letters, digits, - or _: {name!r}")

    icons = data.get("icons", {})
    if not isinstance(icons, dict):
        raise ManifestError("icons must be a table.")

    return Manifest(
        entry=entry,
        name=name,
        display_name=_str(data, "display_name"),
        protocol=_enum(Protocol, data, "protocol"),
        category=_enum(Category, data, "category"),
        offline_first=_bool(data, "offline_first"),
        auth_provider=_str(data, "auth_provider", required=False),
        icon_svg=_str(icons, "svg", required=False),
        icon_png=_str(icons, "png", required=False),
        config=_fields(data, "config"),
    )


def check_config(fields: Iterable[Field], values: dict[str, Any]) -> dict[str, Any]:
    """Check settings against an adapter's fields and return them with lowercase keys.

    Keys may be in any case, as read_config reads them. A None value means not set.

    Raises:
        ConfigError: A key isn't a field, is given twice in different case, or has
            a value of the wrong type. The message names the key, never the value,
            which may be a secret.
    """
    try:
        values = lowercase_keys(values.items())
    except ValueError as e:
        raise ConfigError(str(e)) from None
    types = {field.name: field.type for field in fields}
    problems = []
    for key, value in values.items():
        if key not in types:
            problems.append(f"{key} isn't a setting of this adapter")
        elif value is not None and (expected := _type_problem(value, types[key])):
            problems.append(f"{key} must be {expected}")
    if problems:
        raise ConfigError("; ".join(problems) + ".")
    return values


def missing_config(fields: Iterable[Field], values: dict[str, Any]) -> list[str]:
    """Return the required fields that have no value, or an empty one."""
    return [
        field.name
        for field in fields
        if field.required and values.get(field.name) in (None, "", [])
    ]


def _fields(data: dict[str, Any], section: str) -> tuple[Field, ...]:
    tables = data.get(section, {})
    if not isinstance(tables, dict):
        raise ManifestError(f"{section} must be a table.")
    fields = []
    for name, table in tables.items():
        label = f"{section}.{name}"
        if not _KEY_RE.match(name):
            raise ManifestError(f"{label} must be lowercase letters, digits or _.")
        if not isinstance(table, dict):
            raise ManifestError(f"{label} must be a table.")
        fields.append(
            Field(
                name=name,
                type=_enum(FieldType, table, "type", FieldType.STRING, label),
                required=_bool(table, "required", label),
                secret=_bool(table, "secret", label),
                description=_str(table, "description", label, required=False),
            )
        )
    return tuple(fields)


def _type_problem(value: Any, kind: FieldType) -> str | None:
    """Describe the type value should have, or return None if it has it."""
    match kind:
        case FieldType.STRING:
            return None if isinstance(value, str) else "a string"
        case FieldType.INTEGER:
            ok = isinstance(value, int) and not isinstance(value, bool)
            return None if ok else "a whole number"
        case FieldType.BOOLEAN:
            return None if isinstance(value, bool) else "true or false"
        case FieldType.LIST:
            ok = isinstance(value, list) and all(isinstance(v, str) for v in value)
            return None if ok else "a list of strings"


def _name(key: str, label: str | None) -> str:
    return f"{label}.{key}" if label else key


def _str(
    data: dict[str, Any], key: str, label: str | None = None, *, required: bool = True
) -> Any:
    value = data.get(key)
    if value is None and not required:
        return None
    if not isinstance(value, str) or not value.strip():
        raise ManifestError(f"{_name(key, label)} must be a non-empty string.")
    return value.strip()


def _bool(data: dict[str, Any], key: str, label: str | None = None) -> bool:
    value = data.get(key, False)
    if not isinstance(value, bool):
        raise ManifestError(f"{_name(key, label)} must be true or false.")
    return value


def _enum[E: StrEnum](
    cls: type[E],
    data: dict[str, Any],
    key: str,
    default: E | None = None,
    label: str | None = None,
) -> E:
    if default is not None and key not in data:
        return default
    value = _str(data, key, label)
    try:
        return cls(value)
    except ValueError:
        choices = ", ".join(member.value for member in cls)
        raise ManifestError(
            f"{_name(key, label)} must be one of {choices}, not {value!r}"
        ) from None
