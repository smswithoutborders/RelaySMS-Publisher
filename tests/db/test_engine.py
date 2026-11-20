# SPDX-License-Identifier: GPL-3.0-only

import dataclasses
import sys
import types

import pytest
from sqlalchemy import Column, Integer, MetaData, Table
from sqlalchemy.exc import IntegrityError

from publisher import db
from publisher.config import DatabaseConfig


@pytest.fixture
def encrypted_engine(tmp_path, monkeypatch):
    config = dataclasses.replace(
        DatabaseConfig.get(),
        sqlite_path=str(tmp_path / "encrypted.db"),
        encryption_enabled=True,
        encryption_key=bytes.fromhex("22" * 32),
    )
    monkeypatch.setattr(DatabaseConfig, "get", classmethod(lambda cls: config))
    db.dispose_engine()
    yield db.get_engine()
    db.dispose_engine()


def test_sqlcipher_errors_are_wrapped(encrypted_engine):
    table = Table("items", MetaData(), Column("id", Integer, primary_key=True))
    table.create(encrypted_engine)

    with encrypted_engine.begin() as conn:
        conn.execute(table.insert().values(id=1))
    with pytest.raises(IntegrityError), encrypted_engine.begin() as conn:
        conn.execute(table.insert().values(id=1))


def test_failing_sqlcipher_integrity_check_is_not_a_value_error(monkeypatch, tmp_path):
    """A failed integrity check raises DatabaseConnectionError, not ValueError.

    Callers catch ValueError around key lookups; a plain ValueError would send
    the connection failure message to clients.
    """

    class FakeDatabaseError(Exception):
        pass

    class FakeConnection:
        def execute(self, statement):
            if "sqlite_master" in statement:
                raise FakeDatabaseError("file is not a database")

        def close(self):
            pass

    fake = types.ModuleType("sqlcipher3")
    fake.connect = lambda *args, **kwargs: FakeConnection()
    fake.DatabaseError = FakeDatabaseError
    monkeypatch.setitem(sys.modules, "sqlcipher3", fake)

    connect = db._make_sqlcipher3_creator(str(tmp_path / "encrypted.db"), b"\x01" * 32)
    with pytest.raises(db.DatabaseConnectionError) as excinfo:
        connect()
    assert not isinstance(excinfo.value, ValueError)
    assert "Wrong key" in str(excinfo.value)
