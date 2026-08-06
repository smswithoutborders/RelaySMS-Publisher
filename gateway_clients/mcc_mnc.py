# SPDX-License-Identifier: GPL-3.0-only
"""MCC/MNC (PLMN) lookup: checks mcc_mnc_overrides.json first, then falls
back to the vendored mcc_mnc_table.json snapshot. See README.md."""

import json
import os
from pathlib import Path
from typing import List, Optional

BASE_DIR = Path(__file__).resolve().parent
SNAPSHOT_FILE = BASE_DIR / "mcc_mnc_table.json"
OVERRIDES_FILE = BASE_DIR / "mcc_mnc_overrides.json"

_snapshot_cache: Optional[List[dict]] = None
_overrides_cache: List[dict] = []
_overrides_mtime: float = 0.0


def _load_snapshot() -> List[dict]:
    global _snapshot_cache
    if _snapshot_cache is None:
        with open(SNAPSHOT_FILE, "r", encoding="utf-8") as f:
            _snapshot_cache = json.load(f)
    return _snapshot_cache


def _load_overrides() -> List[dict]:
    global _overrides_cache, _overrides_mtime
    try:
        current_mtime = os.stat(OVERRIDES_FILE).st_mtime
    except FileNotFoundError:
        return []

    if current_mtime == _overrides_mtime:
        return _overrides_cache

    with open(OVERRIDES_FILE, "r", encoding="utf-8") as f:
        _overrides_cache = json.load(f)
    _overrides_mtime = current_mtime
    return _overrides_cache


def _save_overrides(records: List[dict]):
    global _overrides_cache, _overrides_mtime
    with open(OVERRIDES_FILE, "w", encoding="utf-8") as f:
        json.dump(records, f, indent=2, sort_keys=True)
        f.write("\n")
    _overrides_cache = records
    _overrides_mtime = os.stat(OVERRIDES_FILE).st_mtime


def _filter(
    records: List[dict],
    country_code: Optional[str] = None,
    network: Optional[str] = None,
    iso: Optional[str] = None,
) -> List[dict]:
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
    country_code: Optional[str] = None,
    network: Optional[str] = None,
    iso: Optional[str] = None,
) -> List[dict]:
    """Match a country calling code, carrier name, and/or ISO region against
    overrides, then the vendored snapshot. Prefer `iso`: NANP countries
    share country code "1", so it alone can't tell them apart."""
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
    iso: Optional[str] = None,
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
