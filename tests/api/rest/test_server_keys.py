# SPDX-License-Identifier: GPL-3.0-only

import base64

import pytest

from publisher import keys
from publisher.db import get_session
from publisher.models.server_identity_key import get_private_key


@pytest.fixture(autouse=True)
def identity_keys(test_db):
    with get_session() as s:
        keys.initialize_server_identity_keys(s)


def test_lists_every_public_key_in_order(client):
    listed = client.get("/v1/server-keys").json()

    assert [k["key_id"] for k in listed] == list(range(256))


def test_get_returns_the_public_half_of_the_identity_key(client):
    body = client.get("/v1/server-keys/7").json()

    with get_session() as s:
        public = get_private_key(s, 7).public_key().public_bytes_raw()
    assert body == {
        "key_id": 7,
        "public_key": base64.urlsafe_b64encode(public).decode(),
    }


@pytest.mark.parametrize("key_id", ["256", "-1", "abc"])
def test_get_rejects_ids_outside_0_255(client, key_id):
    assert client.get(f"/v1/server-keys/{key_id}").status_code == 422
