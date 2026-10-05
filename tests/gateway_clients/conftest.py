# SPDX-License-Identifier: GPL-3.0-only

import pytest

from publisher.gateway_clients import mcc_mnc


@pytest.fixture(autouse=True)
def overrides_file(tmp_path, monkeypatch):
    """An empty MCC/MNC overrides file for each test."""
    path = tmp_path / "mcc_mnc_overrides.json"
    monkeypatch.setattr(mcc_mnc, "OVERRIDES_FILE", path)
    monkeypatch.setattr(mcc_mnc, "_overrides_cache", [])
    monkeypatch.setattr(mcc_mnc, "_overrides_mtime", 0.0)
    return path
