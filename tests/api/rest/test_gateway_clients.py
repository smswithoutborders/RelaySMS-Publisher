# SPDX-License-Identifier: GPL-3.0-only

import pytest

from publisher.gateway_clients.manager import GatewayClientManager


@pytest.fixture(autouse=True)
def clients(app, tmp_path):
    manager = GatewayClientManager(registry_file=tmp_path / "registry.json")
    manager.create_client(
        "+237670000000",
        ["https"],
        country="Cameroon",
        operator="MTN Cameroon",
        operator_code="62401",
    )
    app.state.gateway_client_manager = manager


def test_list_returns_only_the_published_fields(client):
    assert client.get("/v1/gateway-clients").json() == [
        {
            "msisdn": "+237670000000",
            "country": "Cameroon",
            "operator": "MTN Cameroon",
            "operator_code": "62401",
            "protocols": ["https"],
        }
    ]


def test_list_filters_by_country(client):
    assert client.get("/v1/gateway-clients", params={"country": "nigeria"}).json() == []
