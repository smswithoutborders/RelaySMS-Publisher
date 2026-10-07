# SPDX-License-Identifier: GPL-3.0-only

import pytest

from publisher import db
from publisher.gateway_clients import manager


@pytest.fixture(autouse=True)
def clients(test_db):
    with db.get_session() as session:
        manager.create(
            session,
            "+237670000000",
            ["https"],
            country="Cameroon",
            operator="MTN Cameroon",
            operator_code="62401",
        )
        hidden = manager.create(
            session,
            "+237690000000",
            ["sms"],
            country="Cameroon",
            operator="Orange Cameroon",
            operator_code="62402",
        )
        manager.set_enabled(session, hidden, False)


def test_list_returns_only_enabled_clients_and_published_fields(client):
    assert client.get("/v1/gateway-clients").json() == [
        {
            "msisdn": "+237670000000",
            "country": "Cameroon",
            "operator": "MTN Cameroon",
            "operator_code": "62401",
            "protocols": ["https"],
        }
    ]


@pytest.mark.parametrize(
    "params, msisdns",
    [
        ({"country": "CAMEROON"}, ["+237670000000"]),
        ({"msisdn": "+237670000000"}, ["+237670000000"]),
        ({"country": "nigeria"}, []),
    ],
)
def test_list_filters(client, params, msisdns):
    clients = client.get("/v1/gateway-clients", params=params).json()

    assert [c["msisdn"] for c in clients] == msisdns
