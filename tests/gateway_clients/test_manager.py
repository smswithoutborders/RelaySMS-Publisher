# SPDX-License-Identifier: GPL-3.0-only

import pytest

from publisher.gateway_clients.manager import GatewayClientManager

CAMEROON_MTN = "+237670000000"
NIGERIA_MTN = "+2348031234567"
INDIA_AIRTEL = "+919810012345"  # Airtel has several PLMNs in India.
UNRESOLVABLE = "+447700900123"  # phonenumbers has no carrier for this range.


@pytest.fixture
def clients(tmp_path):
    return GatewayClientManager(registry_file=tmp_path / "registry.json")


def test_create_resolves_country_operator_and_plmn(clients, tmp_path):
    client = clients.create_client(CAMEROON_MTN, ["https"])

    assert (client.country, client.operator, client.operator_code) == (
        "Cameroon",
        "MTN Cameroon",
        "62401",
    )
    reloaded = GatewayClientManager(registry_file=tmp_path / "registry.json")
    assert reloaded.list_clients() == [client]


def test_create_refuses_an_ambiguous_operator_until_its_plmn_is_given(clients):
    with pytest.raises(ValueError, match="Multiple PLMNs"):
        clients.create_client(INDIA_AIRTEL, ["sms"])

    client = clients.create_client(INDIA_AIRTEL, ["sms"], operator_code="40410")
    assert client.operator_code == "40410"


def test_create_needs_explicit_details_when_nothing_resolves(clients):
    with pytest.raises(ValueError, match="country, operator, operator_code"):
        clients.create_client(UNRESOLVABLE, ["sms"])

    client = clients.create_client(
        UNRESOLVABLE,
        ["sms"],
        country="United Kingdom",
        operator="EE",
        operator_code="23430",
    )
    assert client.operator == "EE"


def test_create_rejects_a_registered_msisdn(clients):
    clients.create_client(CAMEROON_MTN, ["https"])

    with pytest.raises(ValueError, match="already registered"):
        clients.create_client(CAMEROON_MTN, ["sms"])


def test_list_filters_case_insensitively(clients):
    clients.create_client(CAMEROON_MTN, ["https"])
    clients.create_client(NIGERIA_MTN, ["sms"])

    assert [c.msisdn for c in clients.list_clients(country="cameroon")] == [
        CAMEROON_MTN
    ]
    assert [c.msisdn for c in clients.list_clients(operator="mtn")] == [NIGERIA_MTN]
    assert clients.list_countries() == ["Cameroon", "Nigeria"]


def test_update_changes_only_the_given_fields(clients):
    clients.create_client(CAMEROON_MTN, ["https"])

    updated = clients.update_client(CAMEROON_MTN, protocols=["https", "sms"])

    assert updated.protocols == ["https", "sms"]
    assert updated.operator_code == "62401"


def test_delete_removes_the_client(clients):
    clients.create_client(CAMEROON_MTN, ["https"])

    clients.delete_client(CAMEROON_MTN)

    assert clients.list_clients() == []
    with pytest.raises(ValueError, match="No gateway client"):
        clients.delete_client(CAMEROON_MTN)
