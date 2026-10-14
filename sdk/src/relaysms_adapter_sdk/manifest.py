# SPDX-License-Identifier: GPL-3.0-only
"""Reads adapter.toml, which describes an adapter to the Publisher."""

import re
import tomllib
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any, assert_never

from relaysms_adapter_sdk.paths import ConfigError as ConfigError
from relaysms_adapter_sdk.paths import lowercase_keys

FILENAME = "adapter.toml"
MAX_FILE_SIZE = 64 * 1024

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
    # A file's text contents. Only setup inputs can be files.
    FILE = "file"


class ManifestError(ValueError):
    pass


@dataclass(frozen=True)
class Field:
    """A setting in a [config] table, or a setup input in a [setup] table."""

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
    setup: tuple[Field, ...] = ()


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
        config=_fields(data, "config", files=False),
        setup=_fields(data, "setup", files=True),
    )


def check_values(
    fields: Iterable[Field], values: dict[str, Any], *, require_all: bool = False
) -> dict[str, Any]:
    """Check values against an adapter's fields and return them with lowercase keys.

    Keys may be in any case, as read_config reads them. A None value means not set.
    With require_all, every required field must also have a value.

    Raises:
        ConfigError: A key isn't a field, is given twice in different case, has a
            value of the wrong type, or is required and missing. The message names
            the key, never the value, which may be a secret.
    """
    fields = tuple(fields)
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
    if require_all:
        problems += [f"{key} is required" for key in missing_values(fields, values)]
    if problems:
        raise ConfigError("; ".join(problems) + ".")
    return values


def missing_values(fields: Iterable[Field], values: dict[str, Any]) -> list[str]:
    """Return the required fields that have no value, or an empty one."""
    return [
        field.name
        for field in fields
        if field.required and not has_value(values.get(field.name))
    ]


def has_value(value: Any) -> bool:
    """Whether a setting counts as set: None, "" and [] don't."""
    return value not in (None, "", [])


def parse_inputs(
    fields: Iterable[Field],
    texts: Iterable[str],
    ask: Callable[[Field], str] | None = None,
    *,
    ask_required: bool = False,
) -> dict[str, Any]:
    """Turn KEY=VALUE command-line inputs into values, with lowercase keys.

    A bare KEY has ask return its value as text; for a file, the file's path.
    With ask_required, ask is also called for each required field not given.
    An unknown KEY=VALUE keeps its text, so check_values reports it with others.
    Every input is checked before anything is asked.

    Raises:
        ConfigError: A key is bare without ask or unknown, is given twice, or its
            value can't be converted (see from_text).
    """
    by_name = {field.name: field for field in fields}
    pairs, asked = [], []
    for text in texts:
        key, equals, value = text.partition("=")
        field = by_name.get(key.lower())
        if equals:
            pairs.append((key, from_text(field, value) if field else value))
        elif ask is None:
            raise ConfigError(f"{key} needs a value, as {key}=VALUE.")
        elif field is None:
            raise ConfigError(f"{key} isn't a setting of this adapter.")
        else:
            asked.append(field)
    if ask_required:
        given = {key.lower() for key, _ in pairs} | {field.name for field in asked}
        asked += [f for f in by_name.values() if f.required and f.name not in given]
    try:
        values = lowercase_keys([*pairs, *((field.name, None) for field in asked)])
    except ValueError as e:
        raise ConfigError(str(e)) from None
    for field in asked:
        assert ask is not None
        answer = ask(field)
        if field.type is FieldType.FILE:
            answer = f"@{answer}"
        values[field.name] = from_text(field, answer)
    return values


def merge_values(current: dict[str, Any], changes: dict[str, Any]) -> dict[str, Any]:
    """Apply checked changes to settings; a None value removes the setting."""
    merged = current | changes
    return {key: value for key, value in merged.items() if value is not None}


def from_text(field: Field, text: str) -> Any:
    """Turn a command-line value into the field's type.

    Lists are comma-separated, and a file is given as @path and read as text.

    Raises:
        ConfigError: The text isn't a value of the field's type, or the file
            can't be read or is over MAX_FILE_SIZE.
    """
    match field.type:
        case FieldType.INTEGER:
            try:
                return int(text)
            except ValueError:
                raise ConfigError(f"{field.name} must be a whole number.") from None
        case FieldType.BOOLEAN:
            if text.lower() not in ("true", "false"):
                raise ConfigError(f"{field.name} must be true or false.")
            return text.lower() == "true"
        case FieldType.LIST:
            return [item.strip() for item in text.split(",") if item.strip()]
        case FieldType.FILE:
            if not text.startswith("@"):
                raise ConfigError(f"{field.name} is a file; give it as @path.")
            return _read_file(field.name, Path(text[1:]).expanduser())
    return text


def _read_file(name: str, path: Path) -> str:
    try:
        with path.open("rb") as file:
            # One byte over the limit is enough to know it's too big.
            data = file.read(MAX_FILE_SIZE + 1)
        text = data.decode("utf-8")
    except (OSError, UnicodeDecodeError) as e:
        raise ConfigError(f"Can't read {path} for {name}: {e}") from e
    if len(data) > MAX_FILE_SIZE:
        raise ConfigError(
            f"{name} must be a file of at most {MAX_FILE_SIZE // 1024} KB."
        )
    return text


def _fields(data: dict[str, Any], section: str, *, files: bool) -> tuple[Field, ...]:
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
        kind = _enum(FieldType, table, "type", FieldType.STRING, label)
        if kind is FieldType.FILE and not files:
            raise ManifestError(f"{label}.type can't be file; only setup inputs can.")
        fields.append(
            Field(
                name=name,
                type=kind,
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
        case FieldType.FILE:
            ok = isinstance(value, str) and len(value.encode()) <= MAX_FILE_SIZE
            return None if ok else f"a file of at most {MAX_FILE_SIZE // 1024} KB"
    return assert_never(kind)


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
