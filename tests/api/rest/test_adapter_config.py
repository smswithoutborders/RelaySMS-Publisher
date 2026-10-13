# SPDX-License-Identifier: GPL-3.0-only

import json
from pathlib import Path

import pytest

from publisher.models.platform_adapter import PNBA
from relaysms_adapter_sdk import UpstreamError
from tests.helpers import add_adapter_with_manifest, get_etag

ADAPTER = "/v1/platforms/adapters/rmail-1"
CONFIG = f"{ADAPTER}/config"
SETUP = f"{ADAPTER}/setup"

MANIFEST = """
entry = "rmail:Adapter"
name = "rmail"
display_name = "RelaySMS Mail"
protocol = "pnba"
category = "email"

[config.smtp_host]
required = true

[config.smtp_password]
required = true
secret = true

[setup.client_file]
type = "file"
required = true
"""

pytestmark = pytest.mark.usefixtures("test_db", "fast_hasher", "platforms_config")


@pytest.fixture
def credentials():
    adapter = add_adapter_with_manifest("rmail", PNBA, MANIFEST)
    path = Path(adapter.config_path) / "credentials.json"
    path.parent.mkdir(parents=True)
    path.write_text('{"smtp_host": "smtp.example", "smtp_password": "hunter2"}')
    return path


def _if_match(client, admin):
    return {**admin, "If-Match": get_etag(client, admin, CONFIG)}


@pytest.mark.parametrize(
    ("method", "url", "body"),
    [
        ("get", CONFIG, None),
        ("patch", CONFIG, {"settings": {}}),
        ("post", SETUP, {"inputs": {}}),
    ],
)
def test_settings_need_an_administrator(client, writer, credentials, method, url, body):
    response = client.request(method, url, json=body, headers=writer)

    assert response.status_code == 403


def test_get_leaves_out_secret_values(client, admin, credentials):
    response = client.get(CONFIG, headers=admin)

    assert response.status_code == 200
    assert "hunter2" not in response.text
    settings = {
        s["name"]: (s["value"], s["is_set"]) for s in response.json()["settings"]
    }
    assert settings == {
        "smtp_host": ("smtp.example", True),
        "smtp_password": (None, True),
    }
    [setup_input] = response.json()["setup"]
    assert (setup_input["name"], setup_input["type"]) == ("client_file", "file")


def test_patch_changes_settings_and_moves_the_etag(client, admin, credentials):
    headers = _if_match(client, admin)

    response = client.patch(
        CONFIG, json={"settings": {"SMTP_HOST": "new"}}, headers=headers
    )

    assert response.status_code == 200, response.text
    assert response.headers["ETag"] != headers["If-Match"]
    assert json.loads(credentials.read_text())["smtp_host"] == "new"
    stale = client.patch(CONFIG, json={"settings": {"smtp_host": "x"}}, headers=headers)
    assert stale.status_code == 412


def test_patch_refuses_unknown_settings(client, admin, credentials):
    response = client.patch(
        CONFIG, json={"settings": {"smtp_hots": "h"}}, headers=_if_match(client, admin)
    )

    assert response.status_code == 400
    assert "smtp_hots isn't a setting" in response.json()["error"]


def test_setup_passes_file_inputs_as_text(client, admin, credentials, adapter_calls):
    adapter_calls.results["setup"] = {
        "settings": {"smtp_host": "h", "smtp_password": "p"}
    }

    # A path is just text here: the server never reads files a client names.
    response = client.post(
        SETUP,
        json={"inputs": {"client_file": "@/etc/hostname"}},
        headers=_if_match(client, admin),
    )

    assert response.status_code == 200, response.text
    [(_, _, request)] = adapter_calls.calls
    assert request.inputs == {"client_file": "@/etc/hostname"}
    assert json.loads(credentials.read_text()) == {
        "smtp_host": "h",
        "smtp_password": "p",
    }


def test_a_failed_setup_is_a_bad_gateway(client, admin, credentials, adapter_calls):
    adapter_calls.results["setup"] = UpstreamError("server down")

    response = client.post(
        SETUP, json={"inputs": {"client_file": "{}"}}, headers=_if_match(client, admin)
    )

    assert response.status_code == 502
    assert "server down" not in response.text


def test_a_broken_file_hides_its_path(client, admin, credentials):
    credentials.write_text("{")

    response = client.get(CONFIG, headers=admin)

    assert response.status_code == 502
    assert str(credentials.parent) not in response.text


def test_the_list_says_whether_an_adapter_is_configured(client, admin, credentials):
    def configured():
        [adapter] = client.get("/v1/platforms/adapters", headers=admin).json()
        return adapter["configured"]

    assert configured() is True
    credentials.write_text('{"smtp_host": "smtp.example"}')
    assert configured() is False
