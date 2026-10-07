# SPDX-License-Identifier: GPL-3.0-only

import datetime

import pytest
from click.testing import CliRunner

from publisher import credentials
from publisher.cli import seed
from publisher.db import get_session
from publisher.gateway_clients import manager
from publisher.models import gateway_client
from publisher.models import platform_adapter as platform_adapters
from publisher.models.publication_stats import PublicationStats

pytestmark = pytest.mark.usefixtures("test_db", "fast_hasher")


def test_stats_adds_realistic_rows_in_batches(monkeypatch):
    monkeypatch.setattr(seed, "BATCH_SIZE", 7)

    result = CliRunner().invoke(seed.cli, ["stats", "--count", "50", "--days", "3"])

    assert result.exit_code == 0, result.output
    with get_session() as db:
        rows = db.query(PublicationStats).all()
    assert len(rows) == 50
    assert all((row.status == "failed") == bool(row.failure_reason) for row in rows)
    times = [row.created_at for row in rows]
    assert max(times) - min(times) <= datetime.timedelta(days=3)


def test_creds_adds_working_non_administrators():
    result = CliRunner().invoke(seed.cli, ["creds", "--count", "4"])

    assert result.exit_code == 0, result.output
    lines = [line.split() for line in result.stdout.splitlines()]
    assert len(lines) == 4
    with get_session() as db:
        for username, password, scope_list in lines:
            credential = credentials.authenticate(db, username, password)
            assert credential is not None
            assert not credential.is_administrator
            assert ",".join(sorted(credential.scopes)) == scope_list


def test_platforms_adds_each_adapter_once():
    first = CliRunner().invoke(seed.cli, ["platforms"])
    again = CliRunner().invoke(seed.cli, ["platforms"])

    assert first.exit_code == 0, first.output
    assert "Added 0 adapter(s)" in again.stdout
    with get_session() as db:
        adapters = platform_adapters.find(db)
    assert {(a.name, a.proto_id) for a in adapters} == {
        (name, proto_id) for name, _, proto_id, _ in seed.ADAPTERS
    }


def test_gateway_clients_adds_resolvable_clients():
    result = CliRunner().invoke(seed.cli, ["gateway-clients", "--count", "8"])

    assert result.exit_code == 0, result.output
    with get_session() as db:
        clients = gateway_client.find(db, include_disabled=True)
    assert len(clients) == 8
    for c in clients:
        candidates = manager.suggest(c.msisdn).candidates
        assert c.operator_code in {candidate.operator_code for candidate in candidates}
