# SPDX-License-Identifier: GPL-3.0-only

import pytest

from publisher import credentials, db
from publisher.gateway_clients import manager
from publisher.gateway_clients.manager import (
    GatewayClientError,
    GatewayClientExistsError,
)
from publisher.models import audit_event
from publisher.models import gateway_client as gateway_clients
from publisher.models.credential import ALL_SCOPES
from tests.helpers import create_credential

CAMEROON_MTN = "+237670000000"
INDIA_AIRTEL = "+919810012345"  # Airtel has several PLMNs in India.
UNKNOWN_CARRIER = "+447700900123"  # A UK drama range.

pytestmark = pytest.mark.usefixtures("test_db", "fast_hasher")


@pytest.fixture
def session():
    with db.get_session() as session:
        yield session


def _events(session):
    """(action, target, details), oldest first."""
    page = audit_event.list_events(session, scopes=ALL_SCOPES, limit=50)
    return [
        (e.action, e.target_label, e.details or {})
        for e in reversed(page.items)
        if e.action.startswith("gateway_clients.")
    ]


def _add(session, msisdn, country, operator, **changes):
    return manager.create(
        session,
        msisdn,
        ["sms"],
        country=country,
        operator=operator,
        operator_code="62401",
        **changes,
    )


def test_create_resolves_country_operator_and_plmn(session):
    client = manager.create(session, CAMEROON_MTN, ["https"])

    assert (client.country, client.operator, client.operator_code) == (
        "Cameroon",
        "MTN Cameroon",
        "62401",
    )
    [(action, target, details)] = _events(session)
    assert (action, target, details["operator_code"]) == (
        "gateway_clients.create",
        CAMEROON_MTN,
        "62401",
    )


def test_given_details_win_over_resolved_ones(session):
    client = manager.create(
        session, CAMEROON_MTN, ["https"], operator="MTN", operator_code="62402"
    )

    assert (client.country, client.operator, client.operator_code) == (
        "Cameroon",
        "MTN",
        "62402",
    )


def test_create_refuses_an_ambiguous_operator_until_its_plmn_is_given(session):
    with pytest.raises(GatewayClientError, match="Multiple PLMNs"):
        manager.create(session, INDIA_AIRTEL, ["sms"])

    client = manager.create(session, INDIA_AIRTEL, ["sms"], operator_code="40410")
    assert client.operator_code == "40410"


def test_create_needs_explicit_details_when_the_carrier_is_unknown(session):
    with pytest.raises(GatewayClientError, match="Could not resolve operator"):
        manager.create(session, UNKNOWN_CARRIER, ["sms"])

    client = manager.create(
        session, UNKNOWN_CARRIER, ["sms"], operator="EE", operator_code="23430"
    )
    assert (client.country, client.operator) == ("United Kingdom", "EE")


@pytest.mark.parametrize(
    "msisdn, protocols, operator_code, error",
    [
        ("237670000000", ["sms"], None, "E.164"),
        (CAMEROON_MTN, [], None, "protocol"),
        (CAMEROON_MTN, ["sms"], "62", "MCC \\+ MNC"),
    ],
)
def test_create_rejects_invalid_input(session, msisdn, protocols, operator_code, error):
    with pytest.raises(GatewayClientError, match=error):
        manager.create(session, msisdn, protocols, operator_code=operator_code)


def test_create_rejects_a_registered_msisdn(session):
    manager.create(session, CAMEROON_MTN, ["https"])

    with pytest.raises(GatewayClientExistsError, match="already registered"):
        manager.create(session, CAMEROON_MTN, ["sms"])


def test_suggest_fills_in_the_plmn_of_an_unambiguous_carrier():
    suggestion = manager.suggest(CAMEROON_MTN)

    assert (suggestion.country, suggestion.iso, suggestion.country_code) == (
        "Cameroon",
        "cm",
        "237",
    )
    assert (suggestion.operator, suggestion.operator_code) == ("MTN Cameroon", "62401")
    assert suggestion.match == "carrier"
    assert suggestion.candidates[0].network == "MTN"


def test_suggest_lists_every_plmn_of_an_ambiguous_carrier():
    suggestion = manager.suggest(INDIA_AIRTEL)

    assert suggestion.match == "carrier"
    assert suggestion.operator_code is None
    assert {"40410", "40553"} <= {c.operator_code for c in suggestion.candidates}


def test_suggest_falls_back_to_every_operator_in_the_region():
    suggestion = manager.suggest(UNKNOWN_CARRIER)

    assert (suggestion.country, suggestion.operator) == ("United Kingdom", None)
    assert suggestion.match == "region"
    assert "Vodafone" in {c.network for c in suggestion.candidates}


@pytest.mark.parametrize("msisdn", ["+999123456789", "not a number"])
def test_suggest_places_nothing_it_cant_parse_or_locate(msisdn):
    suggestion = manager.suggest(msisdn)

    assert (suggestion.match, suggestion.country, suggestion.candidates) == (
        "none",
        None,
        [],
    )


def test_find_filters_case_insensitively_and_hides_disabled(session):
    _add(session, "+237670000001", "Côte d'Ivoire", "Orange")
    disabled = _add(session, "+237670000002", "Cameroon", "MTN")
    manager.set_enabled(session, disabled, False)

    found = gateway_clients.find(session, country="CÔTE D'IVOIRE", operator="orange")
    assert [c.msisdn for c in found] == ["+237670000001"]
    assert gateway_clients.find(session, country="cameroon") == []
    assert len(gateway_clients.find(session, include_disabled=True)) == 2


def test_update_records_what_changed_and_who_changed_it(session):
    create_credential("ops")
    actor = credentials.get_or_raise(session, "ops")
    client = manager.create(session, CAMEROON_MTN, ["https"])

    manager.update(session, client, protocols=["https", "sms"], actor=actor)

    assert client.protocols == ["https", "sms"]
    assert client.operator_code == "62401"
    assert client.updated_by == actor.id
    assert _events(session)[-1] == (
        "gateway_clients.update",
        CAMEROON_MTN,
        {"protocols": {"from": ["https"], "to": ["https", "sms"]}},
    )


def test_update_without_changes_records_nothing(session):
    client = manager.create(session, CAMEROON_MTN, ["https"])
    version = client.version

    manager.update(session, client, protocols=["https"], operator="MTN Cameroon")
    manager.set_enabled(session, client, True)

    assert client.version == version
    assert [action for action, _, _ in _events(session)] == ["gateway_clients.create"]


@pytest.mark.parametrize(
    "changes, error",
    [({"protocols": []}, "protocol"), ({"operator_code": "6"}, "MCC \\+ MNC")],
)
def test_update_rejects_invalid_input(session, changes, error):
    client = manager.create(session, CAMEROON_MTN, ["https"])

    with pytest.raises(GatewayClientError, match=error):
        manager.update(session, client, **changes)


def test_disable_and_enable_are_recorded(session):
    client = manager.create(session, CAMEROON_MTN, ["https"])

    manager.set_enabled(session, client, False)
    manager.set_enabled(session, client, True)

    assert client.is_enabled
    assert [action for action, _, _ in _events(session)][1:] == [
        "gateway_clients.disable",
        "gateway_clients.enable",
    ]


def test_delete_removes_the_client_and_records_its_fields(session):
    client = manager.create(session, CAMEROON_MTN, ["https"])

    manager.delete(session, client)

    assert gateway_clients.find(session, include_disabled=True) == []
    action, target, details = _events(session)[-1]
    assert (action, target, details["protocols"]) == (
        "gateway_clients.delete",
        CAMEROON_MTN,
        ["https"],
    )
    with pytest.raises(GatewayClientError, match="No gateway client"):
        manager.get_or_raise(session, CAMEROON_MTN)
