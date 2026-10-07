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
