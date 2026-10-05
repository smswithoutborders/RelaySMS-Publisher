# SPDX-License-Identifier: GPL-3.0-only

from publisher.gateway_clients import mcc_mnc


def test_the_snapshot_matches_by_region_and_network():
    [match] = mcc_mnc.find_matches(country_code="237", network="mtn", iso="cm")

    assert (match["mcc"], match["mnc"]) == ("624", "01")


def test_overrides_take_precedence_over_the_snapshot(overrides_file):
    mcc_mnc.add_override(
        mcc="624", mnc="99", country_code="237", network="MTN", country="Cameroon"
    )

    [match] = mcc_mnc.find_matches(country_code="237", network="mtn")

    assert (match["mcc"], match["mnc"]) == ("624", "99")
    assert overrides_file.exists()


def test_adding_an_override_again_replaces_it():
    for network in ("Old Name", "New Name"):
        mcc_mnc.add_override(
            mcc="624", mnc="99", country_code="237", network=network, country="CM"
        )

    assert [m["network"] for m in mcc_mnc.find_matches(country_code="237")] == [
        "New Name"
    ]


def test_remove_override_reports_whether_one_existed():
    mcc_mnc.add_override(
        mcc="624", mnc="99", country_code="237", network="MTN", country="Cameroon"
    )

    assert mcc_mnc.remove_override("624", "99") is True
    assert mcc_mnc.remove_override("624", "99") is False
