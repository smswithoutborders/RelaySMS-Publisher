# SPDX-License-Identifier: GPL-3.0-only
"""Custom SQLAlchemy column types and SQL functions."""

import datetime
import json
from typing import Optional

from sqlalchemy import DateTime, LargeBinary, Text, TypeDecorator, cast, func
from sqlalchemy.exc import CompileError
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.sql.expression import FunctionElement, literal_column
from sqlalchemy.sql.visitors import InternalTraversal

from config import DatabaseConfig
from crypto import get_encryption_algorithm
from logutils import get_logger

logger = get_logger(__name__)

DATE_BUCKET_UNITS = ("day", "week", "month", "year")


def utc_now() -> datetime.datetime:
    return datetime.datetime.now(datetime.timezone.utc)


def as_utc(value: Optional[datetime.datetime]) -> Optional[datetime.datetime]:
    """Naive values are assumed to be UTC."""
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=datetime.timezone.utc)
    return value.astimezone(datetime.timezone.utc)


class UTCDateTime(TypeDecorator):
    """Naive UTC in the database, aware UTC in Python."""

    impl = DateTime
    cache_ok = True

    def process_bind_param(self, value, dialect):
        return None if value is None else as_utc(value).replace(tzinfo=None)

    def process_result_value(self, value, dialect):
        return as_utc(value)


class date_bucket(FunctionElement):
    """Start of the day, week (Monday), month or year containing a datetime."""

    type = UTCDateTime()
    name = "date_bucket"
    inherit_cache = True
    _traverse_internals = FunctionElement._traverse_internals + [
        ("unit", InternalTraversal.dp_string)
    ]

    def __init__(self, unit: str, column):
        if unit not in DATE_BUCKET_UNITS:
            raise ValueError(f"Unsupported date bucket unit: {unit!r}")
        self.unit = unit
        super().__init__(column)


def _sql_string(value: str):
    # Inlined, not bound: Postgres needs GROUP BY to match SELECT exactly.
    return literal_column(f"'{value}'")


@compiles(date_bucket)
def _date_bucket_unsupported(element, compiler, **kw):
    raise CompileError(f"date_bucket isn't supported on {compiler.dialect.name}")


@compiles(date_bucket, "postgresql")
def _date_bucket_postgresql(element, compiler, **kw):
    (column,) = element.clauses
    return compiler.process(func.date_trunc(_sql_string(element.unit), column), **kw)


@compiles(date_bucket, "mysql")
def _date_bucket_mysql(element, compiler, **kw):
    (column,) = element.clauses
    day = func.date(column)
    bucket = {
        "day": day,
        "week": func.subdate(day, func.weekday(column)),
        "month": func.date_format(column, _sql_string("%Y-%m-01")),
        "year": func.date_format(column, _sql_string("%Y-01-01")),
    }[element.unit]
    return compiler.process(cast(bucket, DateTime), **kw)


@compiles(date_bucket, "sqlite")
def _date_bucket_sqlite(element, compiler, **kw):
    (column,) = element.clauses
    fmt, *modifiers = {
        "day": ("%Y-%m-%d 00:00:00",),
        "week": ("%Y-%m-%d 00:00:00", "weekday 0", "-6 days"),
        "month": ("%Y-%m-01 00:00:00",),
        "year": ("%Y-01-01 00:00:00",),
    }[element.unit]
    bucket = func.strftime(
        _sql_string(fmt), column, *(_sql_string(m) for m in modifiers)
    )
    return compiler.process(bucket, **kw)


class EncryptedJSON(TypeDecorator):
    """JSON stored as ciphertext when field encryption is enabled."""

    impl = Text
    cache_ok = True

    def __init__(self, algorithm: str = "aes-256-gcm"):
        super().__init__()
        self._encrypt_func, self._decrypt_func = get_encryption_algorithm(algorithm)

    @staticmethod
    def _key() -> bytes | None:
        # Read on each use, so importing models does not need the database settings.
        database = DatabaseConfig.get()
        return (
            database.field_encryption_key if database.field_encryption_enabled else None
        )

    def process_bind_param(self, value, dialect):
        if value is None:
            return None

        json_str = json.dumps(value)
        key = self._key()
        if key is None:
            return json_str
        return self._encrypt_func(key, json_str.encode()).hex()

    def process_result_value(self, value, dialect):
        if value is None:
            return None

        key = self._key()
        if key is None:
            return json.loads(value)
        plaintext = self._decrypt_func(key, bytes.fromhex(value))
        return json.loads(plaintext.decode())


class PrivateEncryptedBinary(TypeDecorator):
    """Binary data always encrypted with DATA_ENCRYPTION_KEY. Used for private keys."""

    impl = LargeBinary
    cache_ok = True

    def __init__(self, algorithm: str = "aes-256-gcm"):
        super().__init__()
        self._encrypt_func, self._decrypt_func = get_encryption_algorithm(algorithm)

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        return self._encrypt_func(DatabaseConfig.get().data_encryption_key, value)

    def process_result_value(self, value, dialect):
        if value is None:
            return None
        return self._decrypt_func(DatabaseConfig.get().data_encryption_key, value)
