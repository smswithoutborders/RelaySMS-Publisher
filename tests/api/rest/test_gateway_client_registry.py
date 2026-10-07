# SPDX-License-Identifier: GPL-3.0-only

import pytest

from tests.helpers import USERNAME, basic_auth, create_credential, get_etag

URL = "/v1/gateway-clients/registry"
MISSING = f"{URL}/00000000-0000-0000-0000-000000000000"
CAMEROON = {
    "msisdn": "+237670000000",
    "protocols": ["https"],
    "country": "Cameroon",
    "operator": "MTN Cameroon",
    "operator_code": "62401",
}
pytestmark = pytest.mark.usefixtures("fast_hasher", "test_db")


def _create(client, admin, **changes):
    response = client.post(URL, json={**CAMEROON, **changes}, headers=admin)
    assert response.status_code == 201, response.text
    return response


def _if_match(client, admin, url):
    return {**admin, "If-Match": get_etag(client, admin, url)}


@pytest.mark.parametrize(
    "method, url, scope",
    [
        ("get", URL, "gc:read"),
        ("post", URL, "gc:write"),
        ("get", MISSING, "gc:read"),
        ("patch", MISSING, "gc:write"),
        ("delete", MISSING, "gc:write"),
        ("get", f"{URL}/suggest?msisdn=%2B237670000000", "gc:write"),
    ],
)
def test_endpoints_require_auth_and_scope(client, method, url, scope):
    assert client.request(method, url).status_code == 401

    headers = basic_auth("viewer", create_credential("viewer", ["platforms:read"]))
    response = client.request(method, url, headers=headers)
    assert response.status_code == 403
    assert response.json()["error"] == f"Missing scope: {scope}."


def test_create_returns_the_client_with_its_location(client, admin):
    response = _create(client, admin)

    data = response.json()
    assert response.headers["location"].endswith(f"{URL}/{data['id']}")
    assert response.headers["etag"]
    assert data["enabled"] is True
    assert (data["created_by"], data["updated_by"]) == (USERNAME, USERNAME)
    assert client.get(URL, headers=admin).json() == [data]


@pytest.mark.parametrize(
    "changes, status",
    [
        ({"msisdn": "237670000000"}, 400),
        ({"protocols": []}, 422),
        ({"unknown": 1}, 422),
    ],
)
def test_create_rejects_invalid_input(client, admin, changes, status):
    response = client.post(URL, json={**CAMEROON, **changes}, headers=admin)
    assert response.status_code == status, response.text


def test_create_refuses_a_registered_msisdn(client, admin):
    _create(client, admin)

    response = client.post(URL, json=CAMEROON, headers=admin)

    assert response.status_code == 409
    assert "already registered" in response.json()["error"]


def test_disabled_clients_are_listed_here_but_not_publicly(client, admin):
    url = f"{URL}/{_create(client, admin).json()['id']}"

    response = client.patch(
        url,
        json={"enabled": False, "protocols": ["sms"]},
        headers=_if_match(client, admin, url),
    )

    assert response.status_code == 200, response.text
    assert response.json()["enabled"] is False
    assert response.json()["protocols"] == ["sms"]
    assert client.get("/v1/gateway-clients").json() == []
    assert len(client.get(URL, headers=admin).json()) == 1


def test_changes_need_the_current_etag(client, admin):
    url = f"{URL}/{_create(client, admin).json()['id']}"
    stale = {**admin, "If-Match": get_etag(client, admin, url)}
    client.patch(url, json={"operator": "MTN"}, headers=stale)

    assert client.delete(url, headers=admin).status_code == 428
    assert client.delete(url, headers=stale).status_code == 412

    fresh = {**admin, "If-Match": get_etag(client, admin, url)}
    assert client.delete(url, headers=fresh).status_code == 204
    assert client.get(url, headers=admin).status_code == 404


def test_changes_are_audited_with_their_actor(client, admin):
    url = f"{URL}/{_create(client, admin).json()['id']}"
    client.patch(url, json={"operator": "MTN"}, headers=_if_match(client, admin, url))
    client.delete(url, headers=_if_match(client, admin, url))

    params = {"target": CAMEROON["msisdn"]}
    events = client.get("/v1/audit-events", params=params, headers=admin).json()

    assert [(e["action"], e["actor"]) for e in events["data"]] == [
        ("gateway_clients.delete", USERNAME),
        ("gateway_clients.update", USERNAME),
        ("gateway_clients.create", USERNAME),
    ]
    assert events["data"][1]["details"] == {
        "operator": {"from": "MTN Cameroon", "to": "MTN"}
    }


def test_patch_without_changes_keeps_the_etag(client, admin):
    url = f"{URL}/{_create(client, admin).json()['id']}"
    headers = _if_match(client, admin, url)

    response = client.patch(url, json={"operator": "MTN Cameroon"}, headers=headers)

    assert response.status_code == 200, response.text
    assert response.headers["etag"] == headers["If-Match"]


def test_patch_rejects_an_invalid_operator_code(client, admin):
    url = f"{URL}/{_create(client, admin).json()['id']}"

    response = client.patch(
        url, json={"operator_code": "6"}, headers=_if_match(client, admin, url)
    )

    assert response.status_code == 400
    assert "MCC + MNC" in response.json()["error"]


@pytest.mark.parametrize("method", ["get", "patch", "delete"])
def test_a_missing_client_is_not_found(client, admin, method):
    headers = {**admin, "If-Match": '"x"'}

    response = client.request(method, MISSING, json={}, headers=headers)

    assert response.status_code == 404


@pytest.mark.parametrize(
    "msisdn, match, has_candidates",
    [
        ("+919810012345", "carrier", True),
        ("+447700900123", "region", True),
        ("+999123456789", "none", False),
    ],
)
def test_suggest_returns_each_kind_of_match(
    client, admin, msisdn, match, has_candidates
):
    response = client.get(f"{URL}/suggest", params={"msisdn": msisdn}, headers=admin)

    assert response.status_code == 200, response.text
    data = response.json()
    assert data["match"] == match
    assert bool(data["candidates"]) is has_candidates
    assert all(set(c) == {"operator_code", "network"} for c in data["candidates"])


def test_suggest_rejects_a_number_not_in_e164(client, admin):
    response = client.get(f"{URL}/suggest", params={"msisdn": "0670000"}, headers=admin)

    assert response.status_code == 400
