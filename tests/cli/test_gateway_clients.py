# SPDX-License-Identifier: GPL-3.0-only

import pytest
from click.testing import CliRunner

from publisher import db
from publisher.cli import gateway_clients as gateway_clients_cli
from publisher.models import gateway_client as gateway_clients

MSISDN = "+237670000000"

pytestmark = pytest.mark.usefixtures("test_db")


def run(*args):
    return CliRunner().invoke(gateway_clients_cli.cli, list(args))


def _clients():
    with db.get_session() as session:
        return [
            (c.msisdn, c.protocols, c.is_enabled)
            for c in gateway_clients.find(session, include_disabled=True)
        ]


def test_create_update_disable_and_delete():
    created = run("create", "--msisdn", MSISDN, "--protocols", "https")
    assert created.exit_code == 0, created.output
    assert "62401" in created.output

    assert run("update", MSISDN, "--protocols", "https,sms").exit_code == 0
    assert run("disable", MSISDN).exit_code == 0
    assert _clients() == [(MSISDN, ["https", "sms"], False)]
    assert MSISDN in run("list").output

    assert run("delete", MSISDN).exit_code == 0
    assert _clients() == []


def test_errors_exit_non_zero():
    result = run("delete", MSISDN)

    assert result.exit_code == 1
    assert "No gateway client found" in result.output


def test_enable_lists_a_disabled_client_again():
    run("create", "--msisdn", MSISDN, "--protocols", "https")
    run("disable", MSISDN)

    assert run("enable", MSISDN).exit_code == 0
    assert _clients() == [(MSISDN, ["https"], True)]


def test_countries_and_operators_include_disabled_clients_once():
    run("create", "--msisdn", MSISDN, "--protocols", "https")
    run("create", "--msisdn", "+237670000001", "--protocols", "sms")
    run("disable", MSISDN)

    assert run("countries").output == "Cameroon\n"
    assert run("operators", "--country", "cameroon").output == "MTN Cameroon\n"


def test_suggest_lists_candidates():
    result = run("suggest", "+919810012345")

    assert result.exit_code == 0, result.output
    assert "MATCH: carrier" in result.output
    assert "40410" in result.output


def test_suggest_rejects_a_number_not_in_e164():
    result = run("suggest", "0670000")

    assert result.exit_code == 2
    assert "E.164" in result.output


def test_mcc_mnc_list_searches_the_snapshot():
    result = run("mcc-mnc", "list", "--iso", "cm", "--network", "mtn")

    assert result.exit_code == 0, result.output
    assert "| 624 | 01  | cm  | Cameroon |" in result.output
