# SPDX-License-Identifier: GPL-3.0-only

from pathlib import Path

import pytest

from relaysms_adapter_sdk import manifest
from relaysms_adapter_sdk.manifest import (
    Category,
    ConfigError,
    Field,
    FieldType,
    ManifestError,
    Protocol,
)

EXAMPLE = Path(__file__).parents[1] / "examples" / "echo-adapter"

MINIMAL = """
entry = "pkg.mod:Cls"
name = "x"
display_name = "X"
protocol = "oauth2"
category = "email"
"""


def test_load_example():
    assert manifest.load(EXAMPLE) == manifest.Manifest(
        entry="echo_adapter:EchoAdapter",
        name="echo",
        display_name="Echo",
        protocol=Protocol.PNBA,
        category=Category.TEXT,
        icon_svg="https://example.com/echo.svg",
        config=(
            Field(
                name="code",
                required=True,
                secret=True,
                description="The code every phone number links with.",
            ),
        ),
    )


def test_defaults():
    parsed = manifest.parse(MINIMAL)
    assert parsed.offline_first is False
    assert parsed.auth_provider is None


def test_missing_file(tmp_path):
    with pytest.raises(ManifestError, match="Can't read"):
        manifest.load(tmp_path)


@pytest.mark.parametrize(
    ("change", "error"),
    [
        ("entry = 'no_class'", "entry must look like"),
        ("name = 'Has Caps'", "name must be"),
        ("display_name = ''", "display_name must be a non-empty string"),
        ("protocol = 'smtp'", "protocol must be one of oauth2, pnba"),
        ("category = 3", "category must be a non-empty string"),
        ("offline_first = 'yes'", "offline_first must be true or false"),
        ("icons = 'x'", "icons must be a table"),
        ("config = 'x'", "config must be a table"),
        ("config.SMTP_HOST = {}", "config.SMTP_HOST must be lowercase"),
        ("config.host = 'x'", "config.host must be a table"),
        ("config.host = {type = 'url'}", "config.host.type must be one of"),
        ("config.host = {secret = 'yes'}", "config.host.secret must be true or false"),
        ("config.host = {description = ''}", "config.host.description must be"),
    ],
)
def test_invalid(change, error):
    key = change.split(" = ")[0]
    lines = [line for line in MINIMAL.splitlines() if not line.startswith(key)]
    with pytest.raises(ManifestError, match=error):
        manifest.parse("\n".join([change, *lines]))


FIELDS = (
    Field("host", required=True),
    Field("port", FieldType.INTEGER),
    Field("tls", FieldType.BOOLEAN),
    Field("scopes", FieldType.LIST),
)


def test_check_config_accepts_each_type_and_none():
    values = {"host": "h", "port": 465, "tls": False, "scopes": ["a"]}
    assert manifest.check_config(FIELDS, values) == values
    assert manifest.check_config(FIELDS, {"host": None}) == {"host": None}


def test_check_config_lowercases_keys():
    assert manifest.check_config(FIELDS, {"HOST": "h"}) == {"host": "h"}
    with pytest.raises(ConfigError, match="set twice"):
        manifest.check_config(FIELDS, {"HOST": "a", "host": "b"})


def test_check_config_names_keys_but_not_values():
    with pytest.raises(ConfigError) as error:
        manifest.check_config(
            FIELDS,
            {"port": True, "tls": "yes", "scopes": [1], "sl_api_key": "sk_live_1"},
        )

    message = str(error.value)
    assert "port must be a whole number" in message
    assert "tls must be true or false" in message
    assert "scopes must be a list of strings" in message
    assert "sl_api_key isn't a setting" in message
    assert "sk_live_1" not in message


@pytest.mark.parametrize("host", [None, "", []])
def test_unset_required_fields_are_missing(host):
    assert manifest.missing_config(FIELDS, {"host": host}) == ["host"]


def test_set_required_fields_are_not_missing():
    assert manifest.missing_config(FIELDS, {"host": "h"}) == []


def test_invalid_toml():
    with pytest.raises(ManifestError, match="Invalid TOML"):
        manifest.parse("entry = ")
