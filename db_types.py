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

from crypto import get_encryption_algorithm
from utils import get_configs, get_logger

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
    """Encrypted JSON type using configurable encryption algorithm."""

    impl = Text
    cache_ok = True

    def __init__(self, algorithm: str = "aes-256-gcm"):
        super().__init__()
        self._encryption_enabled = (
            get_configs(
                "DATABASE_FIELD_ENCRYPTION_ENABLED", default_value="false"
            ).lower()
            == "true"
        )
        self._key = None
        self._encrypt_func = None
        self._decrypt_func = None

        if self._encryption_enabled:
            key_hex = get_configs("DATABASE_FIELD_ENCRYPTION_KEY")
            if not key_hex:
                raise ValueError(
                    "DATABASE_FIELD_ENCRYPTION_KEY required when encryption enabled"
                )

            try:
                self._key = bytes.fromhex(key_hex)
                if len(self._key) != 32:
                    raise ValueError(
                        "DATABASE_FIELD_ENCRYPTION_KEY must be 32 bytes (64 hex chars)"
                    )
            except ValueError as e:
                raise ValueError(f"Invalid DATABASE_FIELD_ENCRYPTION_KEY: {e}")

            self._encrypt_func, self._decrypt_func = get_encryption_algorithm(algorithm)

    def process_bind_param(self, value, dialect):
        """Encrypt JSON before storing."""
        if value is None:
            return None

        json_str = json.dumps(value)

        if not self._encryption_enabled or not self._key:
            return json_str

        ciphertext = self._encrypt_func(self._key, json_str.encode())
        return ciphertext.hex()

    def process_result_value(self, value, dialect):
        """Decrypt JSON after retrieving."""
        if value is None:
            return None

        if not self._encryption_enabled or not self._key:
            return json.loads(value)

        data = bytes.fromhex(value)
        plaintext = self._decrypt_func(self._key, data)
        return json.loads(plaintext.decode())


class PrivateEncryptedBinary(TypeDecorator):
    """
    Mandatory encrypted binary type for private keys.
    Uses DATA_ENCRYPTION_KEY regardless of other encryption settings.
    """

    impl = LargeBinary
    cache_ok = True

    def __init__(self, algorithm: str = "aes-256-gcm"):
        super().__init__()
        key_hex = get_configs("DATA_ENCRYPTION_KEY")
        if not key_hex:
            raise ValueError("DATA_ENCRYPTION_KEY required for PrivateEncryptedBinary")

        try:
            self._key = bytes.fromhex(key_hex)
            if len(self._key) != 32:
                raise ValueError("DATA_ENCRYPTION_KEY must be 32 bytes (64 hex chars)")
        except ValueError as e:
            raise ValueError(f"Invalid DATA_ENCRYPTION_KEY: {e}")

        self._encrypt_func, self._decrypt_func = get_encryption_algorithm(algorithm)

    def process_bind_param(self, value, dialect):
        """Encrypt binary data before storing."""
        if value is None:
            return None
        return self._encrypt_func(self._key, value)

    def process_result_value(self, value, dialect):
        """Decrypt binary data after retrieving."""
        if value is None:
            return None
        return self._decrypt_func(self._key, value)
