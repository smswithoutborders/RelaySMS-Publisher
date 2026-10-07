# SPDX-License-Identifier: GPL-3.0-only

import pytest

from publisher.gateway_clients import mcc_mnc


def _networks(carrier, iso, country_code):
    rows = mcc_mnc.match_carrier(carrier, mcc_mnc.region_operators(iso, country_code))
    return [(r["mcc"] + r["mnc"], r["network"]) for r in rows]


@pytest.mark.parametrize(
    "carrier, iso, country_code, expected",
    [
        # The country's name and company-type words are ignored.
        ("MTN Cameroon", "cm", 237, [("62401", "MTN")]),
        ("Glo Mobile Nigeria", "ng", 234, [("62150", "Glo Mobile")]),
        # Words split differently, or one of several "/" names.
        ("Beeline", "uz", 998, [("43404", "Bee Line/Unitel")]),
        # NANP regions share calling code 1, so the region decides.
        ("Viva", "do", 1, [("37004", "Viva")]),
        # Guernsey has no rows of its own and uses the UK's.
        ("Sure", "gg", 44, [("23455", "Sure Guernsey")]),
    ],
)
def test_carriers_match_their_networks(carrier, iso, country_code, expected):
    assert _networks(carrier, iso, country_code)[: len(expected)] == expected


def test_generic_words_alone_dont_match():
    assert _networks("Mobile FX Services Ltd", "gb", 44) == []


def test_every_matching_row_is_kept_with_exact_names_first():
    matches = _networks("Airtel", "in", 91)

    assert matches[0] == ("40553", "AirTel")
    assert ("40410", "Bharti Airtel Limited (Delhi)") in matches


def test_rows_that_arent_operators_are_left_out():
    networks = {r["network"].casefold() for r in mcc_mnc.find_matches()}

    assert not networks & {"", "fix line", "failed calls", "unknown"}


def test_find_matches_searches_the_snapshot_ignoring_case_and_accents():
    [match] = mcc_mnc.find_matches(country_code="237", network="mtn", iso="cm")
    assert (match["mcc"], match["mnc"]) == ("624", "01")

    assert mcc_mnc.find_matches(network="TELEFÓNICA") == mcc_mnc.find_matches(
        network="telefonica"
    )
