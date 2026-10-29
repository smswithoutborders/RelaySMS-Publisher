# SPDX-License-Identifier: GPL-3.0-only

import json

import pytest

from publisher.config import PlatformsConfig
from tests.helpers import add_adapter

CLIENT_METADATA = {
    "client_id": "https://example.com/v1/platforms/bluesky/oauth/client-metadata.json",
    "dpop_bound_access_tokens": True,
    "application_type": "web",
    "redirect_uris": ["https://example.com/callback"],
    "grant_types": ["authorization_code", "refresh_token"],
    "response_types": ["code"],
    "scope": "atproto transition:generic",
    "token_endpoint_auth_method": "none",
    "client_name": "RelaySMS",
    "client_uri": "https://example.com",
}


@pytest.fixture(autouse=True)
def adapters(test_db):
    add_adapter("bluesky", proto_id=0, cat_id=2)


def test_list_hides_server_paths(client):
    [platform] = client.get("/v1/platforms").json()

    assert platform["name"] == "bluesky"
    assert (
        not {"id", "path", "venv_path", "config_path", "state_path"} & platform.keys()
    )


def test_list_filters_by_protocol(client):
    assert client.get("/v1/platforms", params={"proto_id": 1}).json() == []


def test_oauth_callback_escapes_query_values(client):
    response = client.get(
        "/v1/platforms/bluesky/oauth/callback", params={"code": "<script>x</script>"}
    )

    assert response.status_code == 200
    assert "<script>" not in response.text
    assert "&lt;script&gt;" in response.text


def test_oauth_callback_is_404_for_unknown_platforms(client):
    assert client.get("/v1/platforms/gmail/oauth/callback").status_code == 404


def test_client_metadata_comes_from_the_config_dir(client, platforms_config):
    config = PlatformsConfig.get().adapters_config_dir / "bluesky-0"
    config.mkdir(parents=True)
    uppercase = {key.upper(): value for key, value in CLIENT_METADATA.items()}
    (config / "credentials.json").write_text(json.dumps(uppercase))

    response = client.get("/v1/platforms/bluesky/oauth/client-metadata.json")

    assert response.status_code == 200
    assert response.json() == CLIENT_METADATA


def test_invalid_client_metadata_hides_the_file_path(client, platforms_config):
    config = PlatformsConfig.get().adapters_config_dir / "bluesky-0"
    config.mkdir(parents=True)
    (config / "credentials.json").write_text("{")

    response = client.get("/v1/platforms/bluesky/oauth/client-metadata.json")

    assert response.status_code == 500
    assert str(config) not in response.text


def test_client_metadata_fills_in_the_fixed_atproto_fields(client, platforms_config):
    config = PlatformsConfig.get().adapters_config_dir / "bluesky-0"
    config.mkdir(parents=True)
    settings = ("client_id", "redirect_uris", "client_name", "client_uri", "scope")
    (config / "credentials.json").write_text(
        json.dumps({key: CLIENT_METADATA[key] for key in settings})
    )

    response = client.get("/v1/platforms/bluesky/oauth/client-metadata.json")

    assert response.json() == CLIENT_METADATA


def test_client_metadata_is_404_without_credentials(client, platforms_config):
    response = client.get("/v1/platforms/bluesky/oauth/client-metadata.json")

    assert response.status_code == 404
