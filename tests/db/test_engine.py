# SPDX-License-Identifier: GPL-3.0-only

import dataclasses

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


def test_failing_sqlcipher_integrity_check_is_not_a_value_error(tmp_path):
    """A failed integrity check raises DatabaseConnectionError, not ValueError.

    Callers catch ValueError around key lookups; a plain ValueError would send
    the connection failure message to clients. Exercise this against a real
    encrypted database opened with the wrong key, which is exactly the failure
    the issue describes.
    """
    sqlcipher3 = pytest.importorskip("sqlcipher3")

    db_path = tmp_path / "encrypted.db"
    key = bytes.fromhex("22" * 32)

    # Create a real SQLCipher database with the correct key.
    conn = sqlcipher3.connect(str(db_path))
    try:
        conn.execute("PRAGMA cipher_compatibility = 4;")
        conn.execute(f"PRAGMA key = \"x'{key.hex()}'\";")
        conn.execute("CREATE TABLE items (id INTEGER PRIMARY KEY);")
        conn.commit()
    finally:
        conn.close()

    # Opening it with a different key makes the sqlite_master check fail.
    wrong_key = bytes.fromhex("11" * 32)
    connect = db._make_sqlcipher3_creator(str(db_path), wrong_key)
    with pytest.raises(db.DatabaseConnectionError) as excinfo:
        connect()
    assert not isinstance(excinfo.value, ValueError)
    assert "Wrong key" in str(excinfo.value)
