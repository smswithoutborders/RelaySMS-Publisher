# SPDX-License-Identifier: GPL-3.0-only

from pathlib import Path

import pytest

from relaysms_adapter_sdk import manifest
from relaysms_adapter_sdk.manifest import Category, ManifestError, Protocol

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
    ],
)
def test_invalid(change, error):
    key = change.split(" = ")[0]
    lines = [line for line in MINIMAL.splitlines() if not line.startswith(key)]
    with pytest.raises(ManifestError, match=error):
        manifest.parse("\n".join([change, *lines]))


def test_invalid_toml():
    with pytest.raises(ManifestError, match="Invalid TOML"):
        manifest.parse("entry = ")
