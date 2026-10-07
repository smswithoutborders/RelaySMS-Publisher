# SPDX-License-Identifier: GPL-3.0-only

import pytest

from publisher import db
from publisher.models import platform_adapter as platform_adapters
from publisher.models.platform_adapter import OAUTH2
from tests.helpers import (
    USERNAME,
    add_adapter,
    basic_auth,
    create_credential,
    get_etag,
    link_account,
)

URL = "/v1/platforms/adapters"
GMAIL = f"{URL}/gmail-0"

pytestmark = pytest.mark.usefixtures("fast_hasher", "platforms_config")


@pytest.fixture(autouse=True)
def gmail(test_db):
    add_adapter("gmail", OAUTH2)


def _if_match(client, admin):
    return {**admin, "If-Match": get_etag(client, admin, GMAIL)}


@pytest.mark.parametrize(
    "method, url, scope",
    [
        ("get", URL, "platforms:read"),
        ("get", GMAIL, "platforms:read"),
        ("patch", GMAIL, "platforms:write"),
        ("delete", GMAIL, "platforms:write"),
    ],
)
def test_endpoints_require_auth_and_scope(client, method, url, scope):
    assert client.request(method, url).status_code == 401

    headers = basic_auth("viewer", create_credential("viewer", ["gc:read"]))
    response = client.request(method, url, headers=headers)
    assert response.status_code == 403
    assert response.json()["error"] == f"Missing scope: {scope}."


def test_disabled_adapters_are_listed_but_hidden_from_users(client, admin):
    response = client.patch(
        GMAIL, json={"enabled": False}, headers=_if_match(client, admin)
    )

    assert response.status_code == 200
    [adapter] = client.get(URL, headers=admin).json()
    assert adapter["id"] == "gmail-0"
    assert adapter["source_url"].endswith("/gmail")
    assert adapter["enabled"] is False
    assert (adapter["created_by"], adapter["updated_by"]) == (None, USERNAME)
    assert client.get("/v1/platforms").json() == []
    with db.get_session() as session:
        with pytest.raises(NotImplementedError):
            platform_adapters.get_for_protocol(session, "gmail", OAUTH2)
        assert platform_adapters.get_for_protocol(
            session, "gmail", OAUTH2, include_disabled=True
        )


@pytest.mark.parametrize("if_match, status", [(None, 428), ('"stale"', 412)])
def test_changes_need_the_current_etag(client, admin, if_match, status):
    headers = {**admin, "If-Match": if_match} if if_match else admin

    patched = client.patch(GMAIL, json={"enabled": False}, headers=headers)
    assert patched.status_code == status
    assert client.delete(GMAIL, headers=headers).status_code == status


def test_delete_is_refused_while_accounts_are_linked(client, admin):
    link_account("gmail", OAUTH2)

    response = client.delete(GMAIL, headers=_if_match(client, admin))

    assert response.status_code == 409
    assert "disable it instead" in response.json()["error"].lower()
    assert client.get(GMAIL, headers=admin).status_code == 200


def test_delete_uninstalls_and_records_it(client, admin):
    response = client.delete(GMAIL, headers=_if_match(client, admin))

    assert response.status_code == 204
    assert client.get(GMAIL, headers=admin).status_code == 404
    [event] = client.get(
        "/v1/audit-events", headers=admin, params={"action": "platforms.remove"}
    ).json()["data"]
    assert (event["actor"], event["target"]) == (USERNAME, "gmail")
