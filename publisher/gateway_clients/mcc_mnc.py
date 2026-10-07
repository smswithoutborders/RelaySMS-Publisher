# SPDX-License-Identifier: GPL-3.0-only
"""MCC/MNC (PLMN) lookup in the vendored mcc_mnc_table.json snapshot.

See docs/gateway-clients.md.
"""

import json
import re
import unicodedata
from collections import Counter
from functools import cache
from pathlib import Path

import phonenumbers

SNAPSHOT_FILE = Path(__file__).resolve().parent / "mcc_mnc_table.json"

# Words that say what kind of company it is, not which one.
_GENERIC = frozenset(
    """
    mobile mobil mobility movil movel celular celulares cellular cell wireless
    telecom telecoms telekom telecommunication telecommunications telekomunikasi
    telecomunicacoes telecomunicaciones telefonia communications communication
    comunicacion comunicaciones network networks net broadband gsm cdma lte 3g 4g 5g
    international group services service company co corp inc ltd limited llc plc
    pte pt tbk sa ag ab as asa oy bv nv gmbh srl spa sarl sas sasu sprl sl ltda
    sociedad comercial kft zrt doo ooo oao jsc pjsc bhd sdn pvt private holdings
    solutions systems technologies technology global the of and de do y e et
    """.split()  # noqa: SIM905  (one word per line would run to 100 lines)
)
# Snapshot rows that aren't operators.
_NOT_OPERATORS = frozenset({"", "failed calls", "fix line", "unknown"})
# A word in this many of a region's networks only weakly tells them apart.
_COMMON_IN_REGION = 3


@cache
def _load_snapshot() -> list[dict]:
    """Operator rows, with names trimmed."""
    with open(SNAPSHOT_FILE, encoding="utf-8") as f:
        rows = json.load(f)
    return [
        {**r, "network": r["network"].strip()}
        for r in rows
        if r["network"].strip().casefold() not in _NOT_OPERATORS
    ]


def _fold(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text)
    return "".join(c for c in decomposed if not unicodedata.combining(c)).casefold()


def _words(text: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", _fold(text).replace("&", " and "))


def _aliases(name: str, ignore: frozenset[str]) -> list[list[str]]:
    """Significant words of each part: "Bee Line/Unitel" is [bee, line], [unitel]."""
    aliases = []
    for part in re.split(r"[/()]", name):
        words = [w for w in _words(part) if w not in _GENERIC and w not in ignore]
        if words:
            aliases.append(words)
    return aliases


def _score(
    carrier: list[list[str]], network: list[list[str]], common: frozenset[str]
) -> int:
    """How well two names match, from 3 (the same name) to 0 (no match)."""
    best = 0
    for c in carrier:
        joined_c = "".join(c)
        for n in network:
            joined_n = "".join(n)
            if joined_c == joined_n:
                return 3
            shared = {w for w in set(c) & set(n) if len(w) > 1}
            shorter = min(joined_c, joined_n, key=len)
            # A distinctive shared word, or one name starting the other.
            if (shared - common) or (
                len(shorter) >= 4
                and (joined_c.startswith(joined_n) or joined_n.startswith(joined_c))
            ):
                best = max(best, 2)
            elif shared:
                best = max(best, 1)  # Only words many of the region's networks have.
    return best


def region_operators(iso: str | None, country_code: int) -> list[dict]:
    """Operator rows for a region, or for its calling code's main region.

    The fallback covers territories without rows of their own, like Guernsey.
    """
    main = phonenumbers.region_code_for_country_code(country_code).lower()
    return (find_matches(iso=iso) if iso else []) or find_matches(iso=main)


def match_carrier(carrier: str, rows: list[dict]) -> list[dict]:
    """Rows whose network matches a carrier name, best first."""
    country = frozenset(w for r in rows for w in _words(r["country"]))
    networks = {r["network"]: _aliases(r["network"], country) for r in rows}
    in_networks = Counter(
        w for a in networks.values() for w in {w for words in a for w in words}
    )
    common = frozenset(w for w, n in in_networks.items() if n >= _COMMON_IN_REGION)

    wanted = _aliases(carrier, country)
    scores = {name: _score(wanted, a, common) for name, a in networks.items()}
    matched = [r for r in rows if scores[r["network"]]]
    return sorted(matched, key=lambda r: -scores[r["network"]])


def find_matches(
    country_code: str | None = None,
    network: str | None = None,
    iso: str | None = None,
) -> list[dict]:
    """Snapshot rows matching a calling code, part of a network name and/or region."""
    cc_term = country_code.strip() if country_code else None
    n_term = _fold(network.strip()) if network else None
    iso_term = iso.strip().lower() if iso else None
    return [
        r
        for r in _load_snapshot()
        if not (cc_term and r["country_code"] != cc_term)
        and not (n_term and n_term not in _fold(r["network"]))
        and not (iso_term and r["iso"] != iso_term)
    ]
