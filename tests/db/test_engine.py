# SPDX-License-Identifier: GPL-3.0-only

import dataclasses

import pytest
from sqlalchemy import Column, Integer, MetaData, String, Table
from sqlalchemy.exc import IntegrityError

from publisher import db
from publisher.config import DatabaseConfig

ENCRYPTED = {"encryption_enabled": True, "encryption_key": bytes.fromhex("22" * 32)}


@pytest.fixture
def make_engine(tmp_path, monkeypatch):
    def make(sqlite_path=None, **settings):
        config = dataclasses.replace(
            DatabaseConfig.get(),
            sqlite_path=sqlite_path or str(tmp_path / "test.db"),
            **settings,
        )
        monkeypatch.setattr(DatabaseConfig, "get", classmethod(lambda cls: config))
        db.dispose_engine()
        return db.get_engine()

    yield make
    db.dispose_engine()


def test_sqlcipher_errors_are_wrapped(make_engine):
    engine = make_engine(**ENCRYPTED)
    table = Table("items", MetaData(), Column("id", Integer, primary_key=True))
    table.create(engine)

    with engine.begin() as conn:
        conn.execute(table.insert().values(id=1))
    with pytest.raises(IntegrityError), engine.begin() as conn:
        conn.execute(table.insert().values(id=1))


@pytest.mark.parametrize(
    "settings",
    [{}, {"sqlite_path": ":memory:"}, ENCRYPTED],
    ids=["file", "memory", "encrypted"],
)
def test_database_errors_leave_out_query_parameters(make_engine, settings):
    engine = make_engine(**settings)
    table = Table("notes", MetaData(), Column("body", String, primary_key=True))
    table.create(engine)
    with engine.begin() as conn:
        conn.execute(table.insert().values(body="secret-body"))

    with pytest.raises(IntegrityError) as error, engine.begin() as conn:
        conn.execute(table.insert().values(body="secret-body"))

    assert "secret-body" not in str(error.value)
