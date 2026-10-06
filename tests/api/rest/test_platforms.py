# SPDX-License-Identifier: GPL-3.0-only

import pytest

from tests.helpers import add_adapter


@pytest.fixture(autouse=True)
def adapters(test_db):
    add_adapter("bluesky", proto_id=0, cat_id=2)


def test_list_hides_server_paths(client):
    [platform] = client.get("/v1/platforms").json()

    assert platform["name"] == "bluesky"
    assert not {"id", "path", "venv_path", "assets_path"} & platform.keys()


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
