import sys
from pathlib import Path

from alembic import context

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from db import Base, _build_mysql_url, _build_sqlite_url, _has_mysql_config, get_engine
from models import (
    ClientEphemeralKey,
    PayloadSegment,
    PayloadSession,
    Publication,
    ServerEphemeralKey,
    Token,
    TokenHash,
)
from utils import get_configs

config = context.config
target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """Run migrations in offline mode."""
    engine_type = get_configs("DATABASE_DIALECT", default_value="sqlite")

    if engine_type.lower() == "mysql" and _has_mysql_config():
        url = _build_mysql_url()
    else:
        url = _build_sqlite_url()

    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in online mode."""
    connectable = get_engine()

    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
