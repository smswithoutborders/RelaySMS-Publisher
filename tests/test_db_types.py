# SPDX-License-Identifier: GPL-3.0-only

import datetime

import pytest
import sqlalchemy as sa
from sqlalchemy.dialects import mysql, postgresql

from db_types import DATE_BUCKET_UNITS, UTCDateTime, date_bucket

CREATED_AT = sa.table("t", sa.column("created_at", UTCDateTime())).c.created_at


def _sql(unit, dialect):
    return str(date_bucket(unit, CREATED_AT).compile(dialect=dialect))


def test_postgresql_sql():
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
def test_mysql_sql(unit, expected):
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
def test_sqlite_buckets(value, expected):
    engine = sa.create_engine("sqlite://")
    with engine.connect() as conn:
        row = conn.execute(
            sa.select(
                *(date_bucket(unit, sa.literal(value)) for unit in DATE_BUCKET_UNITS)
            )
        ).one()

    assert [bucket.date().isoformat() for bucket in row] == expected
    assert all(bucket.tzinfo == datetime.timezone.utc for bucket in row)


def test_each_unit_gets_its_own_cached_statement():
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


def test_unknown_unit_is_rejected():
    with pytest.raises(ValueError):
        date_bucket("hour", CREATED_AT)
