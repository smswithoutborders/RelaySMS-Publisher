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


CODE = Field(
    name="code",
    required=True,
    secret=True,
    description="The code every phone number links with.",
)


def test_load_example():
    assert manifest.load(EXAMPLE) == manifest.Manifest(
        entry="echo_adapter:EchoAdapter",
        name="echo",
        display_name="Echo",
        protocol=Protocol.PNBA,
        category=Category.TEXT,
        icon_svg="https://example.com/echo.svg",
        config=(CODE,),
        setup=(CODE,),
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
        ("config.key = {type = 'file'}", "config.key.type can't be file"),
        ("setup.key = {type = 'url'}", "setup.key.type must be one of"),
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


def test_check_values_accepts_each_type_and_none():
    values = {"host": "h", "port": 465, "tls": False, "scopes": ["a"]}
    assert manifest.check_values(FIELDS, values) == values
    assert manifest.check_values(FIELDS, {"host": None}) == {"host": None}


def test_check_values_lowercases_keys():
    assert manifest.check_values(FIELDS, {"HOST": "h"}) == {"host": "h"}
    with pytest.raises(ConfigError, match="set twice"):
        manifest.check_values(FIELDS, {"HOST": "a", "host": "b"})


def test_check_values_names_keys_but_not_values():
    with pytest.raises(ConfigError) as error:
        manifest.check_values(
            FIELDS,
            {"port": True, "tls": "yes", "scopes": [1], "sl_api_key": "sk_live_1"},
        )

    message = str(error.value)
    assert "port must be a whole number" in message
    assert "tls must be true or false" in message
    assert "scopes must be a list of strings" in message
    assert "sl_api_key isn't a setting" in message
    assert "sk_live_1" not in message


def test_check_values_can_require_every_required_field():
    assert manifest.check_values(FIELDS, {}) == {}
    with pytest.raises(ConfigError, match="host is required"):
        manifest.check_values(FIELDS, {"port": 1}, require_all=True)


def test_files_have_a_size_limit():
    key_file = (Field("key_file", FieldType.FILE),)
    small = "x" * manifest.MAX_FILE_SIZE
    assert manifest.check_values(key_file, {"key_file": small})
    with pytest.raises(ConfigError, match="key_file must be a file of at most 64 KB"):
        manifest.check_values(key_file, {"key_file": small + "x"})


@pytest.mark.parametrize(
    ("field", "text", "value"),
    [
        (Field("name"), "RelaySMS", "RelaySMS"),
        (Field("port", FieldType.INTEGER), "465", 465),
        (Field("tls", FieldType.BOOLEAN), "False", False),
        (
            Field("uris", FieldType.LIST),
            "https://a, https://b,",
            ["https://a", "https://b"],
        ),
    ],
)
def test_from_text(field, text, value):
    assert manifest.from_text(field, text) == value


CLIENT_FILE = Field("client_file", FieldType.FILE)


def test_from_text_reads_files(tmp_path):
    (tmp_path / "client.json").write_text('{"web": {}}')
    assert manifest.from_text(CLIENT_FILE, f"@{tmp_path}/client.json") == '{"web": {}}'


@pytest.mark.parametrize(
    ("text", "error"),
    [
        ("{tmp}/client.json", "give it as @path"),
        ("@{tmp}/missing.json", "Can't read"),
        ("@{tmp}/big.json", "at most 64 KB"),
    ],
)
def test_from_text_refuses_bad_files(tmp_path, text, error):
    (tmp_path / "client.json").write_text("{}")
    (tmp_path / "big.json").write_text("x" * (manifest.MAX_FILE_SIZE + 1))
    with pytest.raises(ConfigError, match=error):
        manifest.from_text(CLIENT_FILE, text.format(tmp=tmp_path))


def test_parse_inputs():
    fields = (Field("port", FieldType.INTEGER),)
    assert manifest.parse_inputs(fields, ["PORT=465", "colour=red"]) == {
        "port": 465,
        "colour": "red",
    }


@pytest.mark.parametrize(
    ("texts", "error"),
    [(["port"], "port needs a value"), (["PORT=1", "port=2"], "set twice")],
)
def test_parse_inputs_refuses(texts, error):
    with pytest.raises(ConfigError, match=error):
        manifest.parse_inputs((Field("port", FieldType.INTEGER),), texts)


@pytest.mark.parametrize(
    ("field", "text"),
    [
        (Field("port", FieldType.INTEGER), "465a"),
        (Field("tls", FieldType.BOOLEAN), "yes"),
    ],
)
def test_from_text_rejects_other_types(field, text):
    with pytest.raises(ConfigError, match=field.name):
        manifest.from_text(field, text)


def test_parse_inputs_asks_for_bare_keys(tmp_path):
    (tmp_path / "client.json").write_text("{}")
    fields = (Field("port", FieldType.INTEGER), CLIENT_FILE)
    answers = {"port": "465", "client_file": str(tmp_path / "client.json")}

    values = manifest.parse_inputs(
        fields, ["PORT", "client_file"], lambda field: answers[field.name]
    )

    assert values == {"port": 465, "client_file": "{}"}


def test_parse_inputs_can_ask_for_required_fields_not_given():
    fields = (Field("name", required=True), Field("port", FieldType.INTEGER))
    asked = []

    def ask(field):
        asked.append(field.name)
        return "RelaySMS"

    values = manifest.parse_inputs(fields, ["port=465"], ask, ask_required=True)

    assert values == {"port": 465, "name": "RelaySMS"}
    assert asked == ["name"]


def test_parse_inputs_checks_every_input_before_asking():
    def ask(field):
        raise AssertionError("asked before the inputs were checked")

    fields = (Field("name"), Field("port", FieldType.INTEGER))
    with pytest.raises(ConfigError, match="port must be a whole number"):
        manifest.parse_inputs(fields, ["name", "port=x"], ask)


def test_parse_inputs_refuses_unknown_bare_keys():
    with pytest.raises(ConfigError, match="colour isn't a setting"):
        manifest.parse_inputs((), ["colour"], lambda field: "")


@pytest.mark.parametrize("host", [None, "", []])
def test_unset_required_fields_are_missing(host):
    assert manifest.missing_values(FIELDS, {"host": host}) == ["host"]


def test_set_required_fields_are_not_missing():
    assert manifest.missing_values(FIELDS, {"host": "h"}) == []


def test_invalid_toml():
    with pytest.raises(ManifestError, match="Invalid TOML"):
        manifest.parse("entry = ")
