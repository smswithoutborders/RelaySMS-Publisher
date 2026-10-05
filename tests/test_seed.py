# SPDX-License-Identifier: GPL-3.0-only

import datetime

from click.testing import CliRunner

import seed
from db import get_session
from models import credential as credentials
from models.publication_stats import PublicationStats
from tests.creds_fixtures import *  # noqa: F403


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
