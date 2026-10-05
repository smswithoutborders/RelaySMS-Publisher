# SPDX-License-Identifier: GPL-3.0-only

import datetime

import pytest
import sqlalchemy as sa
from sqlalchemy.dialects import mysql, postgresql

from publisher import crypto, db, keys
from publisher.config import DatabaseConfig
from publisher.db import types
from publisher.db.types import DATE_BUCKET_UNITS, UTCDateTime, date_bucket
from publisher.models.server_identity_key import get_private_key
from publisher.models.token import Token
from publisher.models.token import create as create_token

CREATED_AT = sa.table("t", sa.column("created_at", UTCDateTime())).c.created_at


def _sql(unit, dialect):
    return str(date_bucket(unit, CREATED_AT).compile(dialect=dialect))


def test_date_bucket_sql_on_postgresql():
    for unit in DATE_BUCKET_UNITS:
        assert _sql(unit, postgresql.dialect()) == f"date_trunc('{unit}', t.created_at)"


@pytest.mark.parametrize(
    "unit, expected",
    [
        ("day", "CAST(date(t.created_at) AS DATETIME)"),
        (
            "week",
            "CAST(subdate(date(t.created_at), weekday(t.created_at)) AS DATETIME)",
        ),
        ("month", "CAST(date_format(t.created_at, '%%Y-%%m-01') AS DATETIME)"),
        ("year", "CAST(date_format(t.created_at, '%%Y-01-01') AS DATETIME)"),
    ],
)
def test_date_bucket_sql_on_mysql(unit, expected):
    assert _sql(unit, mysql.dialect()) == expected


@pytest.mark.parametrize(
    "value, expected",
    [
        # Sunday belongs to the week starting the Monday before.
        (
            "2026-09-06 23:59:59.500000",
            ["2026-09-06", "2026-08-31", "2026-09-01", "2026-01-01"],
        ),
        (
            "2026-09-07 00:00:00.000000",
            ["2026-09-07", "2026-09-07", "2026-09-01", "2026-01-01"],
        ),
        (
            "2026-12-31 10:00:00.000000",
            ["2026-12-31", "2026-12-28", "2026-12-01", "2026-01-01"],
        ),
    ],
)
def test_date_bucket_on_sqlite(value, expected):
    engine = sa.create_engine("sqlite://")
    with engine.connect() as conn:
        row = conn.execute(
            sa.select(
                *(date_bucket(unit, sa.literal(value)) for unit in DATE_BUCKET_UNITS)
            )
        ).one()

    assert [bucket.date().isoformat() for bucket in row] == expected
    assert all(bucket.tzinfo == datetime.UTC for bucket in row)


def test_date_bucket_caches_a_statement_per_unit():
    engine = sa.create_engine("sqlite://")
    value = sa.literal("2026-09-09 12:00:00")
    with engine.connect() as conn:
        first = [
            conn.execute(sa.select(date_bucket(u, value))).scalar()
            for u in DATE_BUCKET_UNITS
        ]
        again = [
            conn.execute(sa.select(date_bucket(u, value))).scalar()
            for u in DATE_BUCKET_UNITS
        ]

    assert first == again
    assert len(set(first)) == len(DATE_BUCKET_UNITS)


def test_date_bucket_rejects_unknown_units():
    with pytest.raises(ValueError):
        date_bucket("hour", CREATED_AT)


def _stored(sql, **params):
    """A column's raw bytes or text, as written to the database."""
    with db.get_session() as s:
        return s.execute(sa.text(sql), params).scalar_one()


@pytest.mark.usefixtures("test_db")
def test_private_keys_are_stored_encrypted():
    with db.get_session() as s:
        keys.initialize_server_identity_keys(s, count=1)
        private_key = get_private_key(s, 0).private_bytes_raw()

    stored = _stored("SELECT private_key FROM server_identity_keys")

    assert private_key not in stored
    assert crypto.decrypt(DatabaseConfig.get().data_encryption_key, stored) == (
        private_key
    )


@pytest.mark.usefixtures("test_db")
@pytest.mark.parametrize("field_key", [None, bytes(range(32))])
def test_token_data_is_encrypted_only_with_field_encryption(monkeypatch, field_key):
    monkeypatch.setattr(types, "_field_encryption_key", lambda: field_key)
    with db.get_session() as s:
        token_id = create_token(
            s, platform="gmail", cat_id=0, proto_id=0, token_data={"token": "s3cret"}
        ).id

    stored = _stored("SELECT token_data FROM tokens WHERE id = :id", id=token_id)

    assert ("s3cret" in stored) is (field_key is None)
    with db.get_session() as s:
        assert s.get(Token, token_id).token_data == {"token": "s3cret"}
