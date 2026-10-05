# SPDX-License-Identifier: GPL-3.0-only
"""MCC/MNC (PLMN) lookup.

Checks mcc_mnc_overrides.json first, then falls back to the vendored
mcc_mnc_table.json snapshot. See README.md.
"""

import json
import os
from functools import cache
from pathlib import Path

from publisher.config import ROOT

SNAPSHOT_FILE = Path(__file__).resolve().parent / "mcc_mnc_table.json"
# Written by the CLI, so it lives with the other runtime data.
OVERRIDES_FILE = ROOT / "gateway_clients" / "mcc_mnc_overrides.json"

_overrides_cache: list[dict] = []
_overrides_mtime: float = 0.0


@cache
def _load_snapshot() -> list[dict]:
    with open(SNAPSHOT_FILE, encoding="utf-8") as f:
        return json.load(f)


def _load_overrides() -> list[dict]:
    global _overrides_cache, _overrides_mtime
    try:
        current_mtime = os.stat(OVERRIDES_FILE).st_mtime
    except FileNotFoundError:
        return []

    if current_mtime == _overrides_mtime:
        return _overrides_cache

    with open(OVERRIDES_FILE, encoding="utf-8") as f:
        _overrides_cache = json.load(f)
    _overrides_mtime = current_mtime
    return _overrides_cache


def _save_overrides(records: list[dict]):
    global _overrides_cache, _overrides_mtime
    with open(OVERRIDES_FILE, "w", encoding="utf-8") as f:
        json.dump(records, f, indent=2, sort_keys=True)
        f.write("\n")
    _overrides_cache = records
    _overrides_mtime = os.stat(OVERRIDES_FILE).st_mtime


def _filter(
    records: list[dict],
    country_code: str | None = None,
    network: str | None = None,
    iso: str | None = None,
) -> list[dict]:
    cc_term = str(country_code).strip() if country_code is not None else None
    n_term = network.strip().lower() if network else None
    iso_term = iso.strip().lower() if iso else None

    return [
        record
        for record in records
        if not (cc_term and str(record["country_code"]).strip() != cc_term)
        and not (n_term and n_term not in record["network"].strip().lower())
        and not (iso_term and record["iso"].strip().lower() != iso_term)
    ]


def find_matches(
    country_code: str | None = None,
    network: str | None = None,
    iso: str | None = None,
) -> list[dict]:
    """Match a calling code, carrier name and/or ISO region to PLMNs.

    Checks overrides, then the vendored snapshot. Prefer `iso`: NANP countries
    share country code "1", so it alone can't tell them apart.
    """
    overrides_matches = _filter(_load_overrides(), country_code, network, iso)
    if overrides_matches:
        return overrides_matches

    return _filter(_load_snapshot(), country_code, network, iso)


def add_override(
    mcc: str,
    mnc: str,
    country_code: str,
    network: str,
    country: str,
    iso: str | None = None,
):
    """Add or replace an override entry, keyed by (mcc, mnc)."""
    overrides = _load_overrides()
    overrides = [o for o in overrides if not (o["mcc"] == mcc and o["mnc"] == mnc)]
    overrides.append(
        {
            "mcc": mcc,
            "mnc": mnc,
            "iso": iso or "",
            "country": country,
            "country_code": country_code,
            "network": network,
        }
    )
    _save_overrides(overrides)


def remove_override(mcc: str, mnc: str) -> bool:
    """Remove an override entry by (mcc, mnc). Returns True if one was removed."""
    overrides = _load_overrides()
    remaining = [o for o in overrides if not (o["mcc"] == mcc and o["mnc"] == mnc)]
    if len(remaining) == len(overrides):
        return False
    _save_overrides(remaining)
    return True
