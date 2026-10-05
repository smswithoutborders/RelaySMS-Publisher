# SPDX-License-Identifier: GPL-3.0-only
"""Database connection and session management."""

from collections.abc import Generator
from contextlib import contextmanager
from pathlib import Path
from urllib.parse import quote, quote_plus

from sqlalchemy import create_engine, event, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, declarative_base, sessionmaker
from sqlalchemy.pool import QueuePool, StaticPool

from config import DatabaseConfig, LoggingConfig, ServerDatabaseConfig
from logutils import get_logger

logger = get_logger(__name__)
Base = declarative_base()

_engine: Engine | None = None
_session_factory: sessionmaker | None = None


def _make_sqlcipher3_creator(db_path: str, key: bytes):
    """Return a function that opens the encrypted SQLCipher database."""
    # sqlcipher3 re-exports its C extension with import *, which pyright can't follow.
    import sqlcipher3

    def connect():
        conn = sqlcipher3.connect(  # pyright: ignore[reportAttributeAccessIssue]
            db_path, check_same_thread=False, timeout=30
        )
        conn.execute("PRAGMA cipher_compatibility = 4;")
        conn.execute(f"PRAGMA key = \"x'{key.hex()}'\";")

        try:
            conn.execute("SELECT count(*) FROM sqlite_master;")
        except sqlcipher3.DatabaseError:  # pyright: ignore[reportAttributeAccessIssue]
            conn.close()
            raise ValueError("Invalid hex key or database file is corrupted.") from None

        return conn

    return connect


def _ensure_sqlite_parent_dir(db_path: str) -> None:
    if db_path == ":memory:":
        return

    parent = Path(db_path).expanduser().resolve().parent
    parent.mkdir(parents=True, exist_ok=True)


def _server_url(driver: str, server: ServerDatabaseConfig) -> str:
    safe_user = quote_plus(server.user or "")
    safe_password = quote_plus(server.password or "")
    safe_database = quote_plus(server.database or "")
    return (
        f"{driver}://{safe_user}:{safe_password}@{server.host}:{server.port}"
        f"/{safe_database}"
    )


def build_url(database: DatabaseConfig) -> str:
    """Return the connection URL for the configured dialect."""
    if database.dialect == "mysql":
        return _server_url("mysql+pymysql", database.mysql)
    if database.dialect == "postgres":
        return _server_url("postgresql+psycopg2", database.postgres)
    return f"sqlite:///{quote(database.sqlite_path, safe='/')}"


def _ensure_mysql_database(server: ServerDatabaseConfig) -> None:
    import pymysql

    safe_db = server.database.replace("`", "``")

    try:
        conn = pymysql.connect(
            host=server.host,
            port=server.port,
            user=server.user,
            password=server.password,
        )
        with conn.cursor() as cursor:
            cursor.execute(
                f"CREATE DATABASE IF NOT EXISTS `{safe_db}` "
                "CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci"
            )
        conn.close()
        logger.debug("Database '%s' ready", server.database)
    except Exception as e:
        logger.error("Failed to create database '%s': %s", server.database, e)
        raise


def _ensure_postgres_database(server: ServerDatabaseConfig) -> None:
    import psycopg2
    from psycopg2 import sql

    try:
        conn = psycopg2.connect(
            host=server.host,
            port=server.port,
            user=server.user,
            password=server.password,
            dbname="postgres",
        )
        conn.autocommit = True
        with conn.cursor() as cursor:
            cursor.execute(
                "SELECT 1 FROM pg_database WHERE datname = %s", (server.database,)
            )
            if cursor.fetchone() is None:
                cursor.execute(
                    sql.SQL("CREATE DATABASE {}").format(
                        sql.Identifier(server.database)
                    )
                )
        conn.close()
        logger.debug("Database '%s' ready", server.database)
    except Exception as e:
        logger.error("Failed to create database '%s': %s", server.database, e)
        raise


def _create_engine() -> Engine:
    # Read when the engine is built, since many processes import db but never use it.
    database = DatabaseConfig.get()

    if database.dialect == "sqlite" and database.sqlite_path == ":memory:":
        # One shared connection, so every session sees the same in-memory database.
        return create_engine(
            "sqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )

    sql_echo = LoggingConfig.get().log_level == "DEBUG"

    if database.dialect == "mysql":
        if database.encryption_enabled:
            logger.info(
                "Database encryption enabled - ensure TDE is configured on "
                "MySQL/MariaDB server"
            )
        _ensure_mysql_database(database.mysql)
    elif database.dialect == "postgres":
        if database.encryption_enabled:
            logger.info(
                "Database encryption enabled - Postgres has no built-in TDE, "
                "use disk-level encryption on the server"
            )
        _ensure_postgres_database(database.postgres)

    if database.dialect != "sqlite":
        engine = create_engine(
            build_url(database), pool_pre_ping=True, pool_recycle=3600
        )
    else:
        _ensure_sqlite_parent_dir(database.sqlite_path)
        if database.encryption_enabled:
            assert database.encryption_key is not None  # config requires it here
            logger.info("Using SQLCipher3 encryption for SQLite")
            engine = create_engine(
                "sqlite://",
                creator=_make_sqlcipher3_creator(
                    database.sqlite_path, database.encryption_key
                ),
                echo=sql_echo,
                poolclass=QueuePool,
                pool_size=5,
                pool_pre_ping=True,
            )
        else:
            engine = create_engine(
                build_url(database),
                echo=sql_echo,
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

    logger.info("Connected to %s database", database.dialect)
    return engine


def get_engine() -> Engine:
    global _engine
    if _engine is None:
        _engine = _create_engine()
    return _engine


def dispose_engine() -> None:
    global _engine, _session_factory
    if _engine is not None:
        _engine.dispose()
        logger.info("Database engine disposed")
        _engine = None
        _session_factory = None


def get_session_factory() -> sessionmaker:
    global _session_factory
    if _session_factory is None:
        _session_factory = sessionmaker(bind=get_engine(), expire_on_commit=False)
    return _session_factory


@contextmanager
def get_session() -> Generator[Session]:
    """Yield a session that commits on success and rolls back on error."""
    session = get_session_factory()()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def get_db() -> Generator[Session]:
    with get_session() as session:
        yield session
