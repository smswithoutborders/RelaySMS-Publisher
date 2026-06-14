# SPDX-License-Identifier: GPL-3.0-only
"""Database connection and session management."""

from contextlib import contextmanager
from pathlib import Path
from typing import Generator, Optional
from urllib.parse import quote, quote_plus

from sqlalchemy import create_engine, event, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, declarative_base, sessionmaker
from sqlalchemy.pool import QueuePool, StaticPool

from logutils import get_logger
from utils import get_configs

logger = get_logger(__name__)
Base = declarative_base()

_engine: Optional[Engine] = None
_session_factory: Optional[sessionmaker] = None


def _build_sqlite_url() -> str:
    """Build SQLite connection URL."""
    db_path = get_configs("SQLITE_DATABASE_PATH", default_value="data/relaysms.db")
    safe_db_path = quote(db_path, safe="/")
    return f"sqlite:///{safe_db_path}"


def _make_sqlcipher3_creator(db_path: str, key: str):
    """Return a SQLAlchemy creator function that opens an encrypted SQLCipher3 database."""
    import sqlcipher3

    def connect():
        conn = sqlcipher3.connect(db_path, check_same_thread=False, timeout=30)
        conn.execute("PRAGMA cipher_compatibility = 4;")
        conn.execute(f"PRAGMA key = \"x'{key}'\";")

        try:
            conn.execute("SELECT count(*) FROM sqlite_master;")
        except sqlcipher3.DatabaseError:
            conn.close()
            raise ValueError("Invalid hex key or database file is corrupted.")

        return conn

    return connect


def _get_sqlcipher3_config():
    """Validate and return (db_path, key) for an encrypted SQLite database."""
    db_path = get_configs("SQLITE_DATABASE_PATH", default_value="data/relaysms.db")
    key = get_configs("DATABASE_ENCRYPTION_KEY")
    if not key:
        raise ValueError(
            "DATABASE_ENCRYPTION_ENABLED=true but DATABASE_ENCRYPTION_KEY is not set"
        )

    try:
        key_bytes = bytes.fromhex(key)
    except ValueError:
        raise ValueError("DATABASE_ENCRYPTION_KEY must be a valid hex string")

    if len(key_bytes) != 32:
        raise ValueError(
            f"DATABASE_ENCRYPTION_KEY must be 32 bytes (64 hex chars), got {len(key_bytes)}"
        )

    logger.info("Using SQLCipher3 encryption for SQLite")
    return db_path, key


def _ensure_sqlite_parent_dir() -> None:
    """Create the SQLite database parent directory if needed."""
    db_path = get_configs("SQLITE_DATABASE_PATH", default_value="data/relaysms.db")
    if not db_path or db_path == ":memory:":
        return

    parent = Path(db_path).expanduser().resolve().parent
    parent.mkdir(parents=True, exist_ok=True)


def _build_mysql_url() -> str:
    """Build MySQL connection URL."""
    host = get_configs("MYSQL_HOST", default_value="localhost")
    port = get_configs("MYSQL_PORT", default_value="3306")
    user = get_configs("MYSQL_USER")
    password = get_configs("MYSQL_PASSWORD")
    database = get_configs("MYSQL_DATABASE")

    if (
        get_configs("DATABASE_ENCRYPTION_ENABLED", default_value="false").lower()
        == "true"
    ):
        logger.info(
            "Database encryption enabled - ensure TDE is configured on MySQL/MariaDB server"
        )

    safe_user = quote_plus(user) if user else ""
    safe_password = quote_plus(password) if password else ""
    safe_database = quote_plus(database) if database else ""

    return f"mysql+pymysql://{safe_user}:{safe_password}@{host}:{port}/{safe_database}"


def _ensure_mysql_database() -> None:
    """Create MySQL database if it doesn't exist."""
    import pymysql

    host = get_configs("MYSQL_HOST", default_value="localhost")
    port = int(get_configs("MYSQL_PORT", default_value="3306"))
    user = get_configs("MYSQL_USER")
    password = get_configs("MYSQL_PASSWORD")
    database = get_configs("MYSQL_DATABASE")

    safe_db = database.replace("`", "``") if database else database

    try:
        conn = pymysql.connect(host=host, port=port, user=user, password=password)
        with conn.cursor() as cursor:
            cursor.execute(
                f"CREATE DATABASE IF NOT EXISTS `{safe_db}` "
                "CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci"
            )
        conn.close()
        logger.debug(f"Database '{database}' ready")
    except Exception as e:
        logger.error(f"Failed to create database '{database}': {e}")
        raise


def _has_mysql_config() -> bool:
    """Check if MySQL configuration is complete."""
    required = ["MYSQL_HOST", "MYSQL_USER", "MYSQL_PASSWORD", "MYSQL_DATABASE"]
    return all(get_configs(key) for key in required)


def _create_engine() -> Engine:
    """Create and configure database engine."""
    mode = get_configs("MODE", default_value="development")
    engine_type = get_configs("DATABASE_DIALECT", default_value="sqlite")

    if mode == "testing":
        logger.debug("Using in-memory SQLite for testing")
        return create_engine(
            "sqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )

    if mode == "development" and engine_type.lower() == "mysql":
        if not _has_mysql_config():
            logger.warning("MySQL config incomplete, falling back to SQLite")
            engine_type = "sqlite"

    if engine_type.lower() == "mysql":
        _ensure_mysql_database()
        url = _build_mysql_url()
        engine = create_engine(url, pool_pre_ping=True, pool_recycle=3600)
    else:
        _ensure_sqlite_parent_dir()
        encrypt = (
            get_configs("DATABASE_ENCRYPTION_ENABLED", default_value="false").lower()
            == "true"
        )
        if encrypt:
            db_path, key = _get_sqlcipher3_config()
            engine = create_engine(
                "sqlite://",
                creator=_make_sqlcipher3_creator(db_path, key),
                echo=False,
                poolclass=QueuePool,
                pool_size=5,
                pool_pre_ping=True,
            )
        else:
            url = _build_sqlite_url()
            engine = create_engine(
                url,
                echo=False,
                connect_args={"check_same_thread": False, "timeout": 30},
                poolclass=QueuePool,
                pool_size=5,
                pool_pre_ping=True,
            )

        @event.listens_for(engine, "connect")
        def set_sqlite_pragma(dbapi_connection, connection_record):
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA synchronous=NORMAL")
            cursor.close()

    with engine.connect() as conn:
        conn.execute(text("SELECT 1"))

    logger.info(f"Connected to {engine_type} database")
    return engine


def get_engine() -> Engine:
    """Get database engine."""
    global _engine
    if _engine is None:
        _engine = _create_engine()
    return _engine


def dispose_engine() -> None:
    """Dispose database engine and cleanup connections."""
    global _engine, _session_factory
    if _engine is not None:
        _engine.dispose()
        logger.info("Database engine disposed")
        _engine = None
        _session_factory = None


def get_session_factory() -> sessionmaker:
    """Get session factory."""
    global _session_factory
    if _session_factory is None:
        _session_factory = sessionmaker(bind=get_engine(), expire_on_commit=False)
    return _session_factory


@contextmanager
def get_session() -> Generator[Session, None, None]:
    """Context manager for database sessions."""
    session = get_session_factory()()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
