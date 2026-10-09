# SPDX-License-Identifier: GPL-3.0-only
"""Reads adapter.toml, which describes an adapter to the Publisher."""

import re
import tomllib
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any

FILENAME = "adapter.toml"

_ENTRY_RE = re.compile(r"^[A-Za-z_][\w.]*:[A-Za-z_]\w*$")
_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9_-]*$")


class Protocol(StrEnum):
    OAUTH2 = "oauth2"
    PNBA = "pnba"


class Category(StrEnum):
    EMAIL = "email"
    MESSAGE = "message"
    TEXT = "text"
    BRIDGE = "bridge"


class ManifestError(ValueError):
    pass


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

    offline_first = data.get("offline_first", False)
    if not isinstance(offline_first, bool):
        raise ManifestError("offline_first must be true or false.")

    return Manifest(
        entry=entry,
        name=name,
        display_name=_str(data, "display_name"),
        protocol=_enum(Protocol, data, "protocol"),
        category=_enum(Category, data, "category"),
        offline_first=offline_first,
        auth_provider=_str(data, "auth_provider", required=False),
        icon_svg=_str(icons, "svg", required=False),
        icon_png=_str(icons, "png", required=False),
    )


def _str(data: dict[str, Any], key: str, *, required: bool = True) -> Any:
    value = data.get(key)
    if value is None and not required:
        return None
    if not isinstance(value, str) or not value.strip():
        raise ManifestError(f"{key} must be a non-empty string.")
    return value.strip()


def _enum[E: StrEnum](cls: type[E], data: dict[str, Any], key: str) -> E:
    value = _str(data, key)
    try:
        return cls(value)
    except ValueError:
        choices = ", ".join(member.value for member in cls)
        raise ManifestError(f"{key} must be one of {choices}, not {value!r}") from None
