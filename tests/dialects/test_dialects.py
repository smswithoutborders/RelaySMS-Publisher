# SPDX-License-Identifier: GPL-3.0-only
"""Migrations and the queries that differ between databases, on each dialect."""

import datetime
import hashlib
import json

import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import LargeBinary, select, text
from sqlalchemy.dialects import mysql
from sqlalchemy.exc import IntegrityError

from publisher import credentials, db, keys
from publisher.credentials import CredentialConflictError, CredentialExistsError
from publisher.db import Base, pagination
from publisher.models import audit_event, publication_stats
from publisher.models import gateway_client as gateway_clients
from publisher.models import platform_adapter_job as jobs
from publisher.models import token as tokens
from publisher.models import token_hash as token_hashes
from publisher.models.audit_event import AuditAction
from publisher.models.credential import ALL_SCOPES
from publisher.models.platform_adapter import PlatformAdapter
from publisher.models.publication_stats import PublicationStats, StatsFilters
from publisher.models.server_identity_key import get_private_key, get_public_keys
from publisher.models.token import Token
from publisher.models.token_hash import TokenHash
from tests.helpers import can_log_in, create_credential

# tests/summary.py groups this module's results by database.
SUMMARY_BY = "dialect"
UTC = datetime.UTC
UNICODE = "Ünïcødé ✉️ 🚀 文字"


def at(*args: int) -> datetime.datetime:
    return datetime.datetime(*args, tzinfo=UTC)  # pyright: ignore[reportArgumentType]


def adapter(adapter_id: str, name: str, proto_id: int) -> PlatformAdapter:
    return PlatformAdapter(
        id=adapter_id,
        source_url=f"https://github.com/smswithoutborders/{name}",
        commit="0" * 40,
        name=name,
        display_name=UNICODE,
        proto_id=proto_id,
        cat_id=0,
    )


def add_stats(*created: datetime.datetime) -> list[int]:
    with db.get_session() as session:
        rows = [
            PublicationStats(status="published", platform_name="gmail", created_at=c)
            for c in created
        ]
        session.add_all(rows)
        session.flush()
        return [row.id for row in rows]


def test_migrations_downgrade_and_upgrade_again(alembic_config):
    command.downgrade(alembic_config, "base")
    command.upgrade(alembic_config, "head")


def test_migration_imports_the_gateway_client_registry(
    alembic_config, tmp_path, monkeypatch
):
    registry = tmp_path / "registry.json"
    client = {
        "msisdn": "+237670000000",
        "country": UNICODE,
        "operator": "MTN Cameroon",
        "operator_code": "62401",
        "protocols": ["https", "sms"],
    }
    incomplete = {"msisdn": "+237690000000", "protocols": ["sms"]}
    registry.write_text(json.dumps({c["msisdn"]: c for c in (client, incomplete)}))
    monkeypatch.setenv("GATEWAY_CLIENTS_REGISTRY_FILE", str(registry))

    command.downgrade(alembic_config, "018")
    command.upgrade(alembic_config, "head")

    with db.get_session() as session:
        assert len(gateway_clients.find(session, include_disabled=True)) == 1
        [imported] = gateway_clients.find(session, country=UNICODE.upper())
        assert (imported.msisdn, imported.protocols) == (
            client["msisdn"],
            ["https", "sms"],
        )


def _same_type(context, inspected_column, metadata_column, inspected, metadata):
    # MySQL creates LargeBinary(32) as TINYBLOB, the smallest blob that fits.
    if (
        isinstance(inspected, mysql.TINYBLOB)
        and isinstance(metadata, LargeBinary)
        and (metadata.length or 256) <= 255
    ):
        return False
    return None


def test_models_match_migrations():
    with db.get_engine().connect() as conn:
        context = MigrationContext.configure(conn, opts={"compare_type": _same_type})
        assert compare_metadata(context, Base.metadata) == []


def test_credential_create_update_and_login(fast_hasher):
    password = create_credential("Ops.Admin", ["creds:read"])

    with db.get_session() as session:
        credential = credentials.get_or_raise(session, "ops.admin")
        credentials.update(session, credential, scopes=["creds:read", "creds:write"])

    assert can_log_in("OPS.ADMIN", password)
    assert not can_log_in("ops.admin", "wrong")
    with db.get_session() as session:
        assert credentials.get_or_raise(session, "ops.admin").scopes == {
            "creds:read",
            "creds:write",
        }
    with pytest.raises(CredentialExistsError), db.get_session() as session:
        credentials.create(session, "ops.admin", ["creds:read"])


def test_concurrent_credential_change_is_refused(fast_hasher):
    create_credential("ops", ["creds:read"])

    first, second = db.get_session_factory()(), db.get_session_factory()()
    try:
        stale = credentials.get_or_raise(first, "ops")
        fresh = credentials.get_or_raise(second, "ops")
        credentials.update(second, fresh, active=False)
        second.commit()

        with pytest.raises(CredentialConflictError):
            credentials.update(first, stale, active=False)
    finally:
        first.close()
        second.close()


def test_timestamps_come_back_as_utc():
    plus_one = datetime.timezone(datetime.timedelta(hours=1))
    (row_id,) = add_stats(datetime.datetime(2026, 3, 1, 0, 30, tzinfo=plus_one))

    with db.get_session() as session:
        created_at = session.get_one(PublicationStats, row_id).created_at

    assert created_at == at(2026, 2, 28, 23, 30)
    assert created_at.tzinfo == UTC


def test_pages_cover_every_row_once_in_both_directions():
    tie = at(2026, 3, 2, 12)
    created = [at(2026, 3, 1), tie, tie, tie, at(2026, 3, 3), at(2026, 3, 4)]
    ids = add_stats(*created)
    times = dict(zip(ids, created, strict=True))
    newest_first = sorted(ids, key=lambda i: (times[i], i), reverse=True)

    pages, cursor = [], None
    with db.get_session() as session:
        while True:
            page = publication_stats.list_stats(
                session, filters=StatsFilters(), limit=2, cursor=cursor
            )
            pages.append([item["id"] for item in page.items])
            if page.next_cursor is None:
                break
            cursor = pagination.decode_cursor(page.next_cursor)

        assert [i for p in pages for i in p] == newest_first

        back = publication_stats.list_stats(
            session,
            filters=StatsFilters(),
            limit=2,
            cursor=pagination.decode_cursor(page.prev_cursor),  # pyright: ignore[reportArgumentType]
        )
        assert [item["id"] for item in back.items] == pages[-2]


@pytest.mark.parametrize(
    ("interval", "expected"),
    [
        ("day", {
            at(2026, 3, 2): 1, at(2026, 3, 4): 1, at(2026, 3, 8): 1,
            at(2026, 3, 9): 1, at(2026, 4, 15): 1,
        }),
        ("week", {at(2026, 3, 2): 3, at(2026, 3, 9): 1, at(2026, 4, 13): 1}),
        ("month", {at(2026, 3, 1): 4, at(2026, 4, 1): 1}),
        ("year", {at(2026, 1, 1): 5}),
    ],
)  # fmt: skip
def test_summary_buckets_by_period(interval, expected):
    # 2026-03-02 and 2026-03-09 are Mondays.
    add_stats(
        at(2026, 3, 2, 0, 0),
        at(2026, 3, 4, 13, 0),
        at(2026, 3, 8, 23, 59, 59),
        at(2026, 3, 9, 0, 0),
        at(2026, 4, 15, 8, 0),
    )
    filters = StatsFilters(since=at(2026, 1, 1), until=at(2027, 1, 1))

    with db.get_session() as session:
        groups = publication_stats.summarize(
            session, group_by=["status"], filters=filters, interval=interval
        )

    assert {group["period"]: group["count"] for group in groups} == expected


def test_adapter_name_and_protocol_are_unique():
    with db.get_session() as session:
        session.add(adapter("gmail-0", "gmail", 0))

    with pytest.raises(IntegrityError), db.get_session() as session:
        session.add(adapter("gmail-copy", "gmail", 0))

    with db.get_session() as session:
        session.add(adapter("gmail-1", "gmail", 1))
        assert session.get_one(PlatformAdapter, "gmail-0").display_name == UNICODE


def create_job(session) -> jobs.PlatformAdapterJob:
    return jobs.create(session, adapter_id="gmail-0", action="install", source_url="x")


def test_one_job_per_adapter_until_it_finishes():
    with db.get_session() as session:
        job = create_job(session)

    with pytest.raises(jobs.JobBusyError), db.get_session() as session:
        create_job(session)

    full_log = ["pip output " + UNICODE] * 10_000
    with db.get_session() as session:
        jobs.finish(session, job.id, state="failed", log=full_log)
    with db.get_session() as session:
        assert session.get_one(jobs.PlatformAdapterJob, job.id).log.endswith(UNICODE)
        create_job(session)


def test_tokens_are_stored_encrypted_and_found_by_hash():
    data = {"account_id": UNICODE, "token": {"access_token": "a" * 5000}}
    with db.get_session() as session:
        token = tokens.create(session, "gmail", 0, 0, data)
        _, raw = token_hashes.create(session, token.id)
        token_pk, token_id = token.id, token.token_id

    with db.get_session() as session:
        stored = session.execute(
            text("SELECT token_data FROM tokens WHERE id = :id"), {"id": token_pk}
        ).scalar_one()
        assert "account_id" not in stored
        assert session.get_one(Token, token_pk).token_data == data
        assert 0 <= token_id < 2**32

        found = session.scalars(
            select(TokenHash).where(
                TokenHash.token_hash == hashlib.sha256(raw).digest()
            )
        ).one()
        assert found.token_id == token_pk


def test_server_identity_keys_round_trip():
    with db.get_session() as session:
        keys.initialize_server_identity_keys(session, count=3)

    with db.get_session() as session:
        public_keys = get_public_keys(session)
        private = get_private_key(session, 2)

    assert [key["key_id"] for key in public_keys] == [0, 1, 2]
    assert len(private.public_key().public_bytes_raw()) == 32


def test_audit_details_keep_json_and_unicode():
    details = {"note": UNICODE, "scopes": sorted(ALL_SCOPES), "count": 3}
    with db.get_session() as session:
        audit_event.record(session, AuditAction.AUTH_LOGIN, actor=None, details=details)

    with db.get_session() as session:
        page = audit_event.list_events(session, scopes=ALL_SCOPES, limit=10)

    assert [event.details for event in page.items] == [details]
