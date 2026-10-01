import sys
from pathlib import Path

from alembic import context

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from config import DatabaseConfig
from db import Base, build_url, get_engine
from models import (
    AdminSession,
    AdminUser,
    ClientEphemeralKey,
    PayloadSegment,
    PayloadSession,
    PublicationStats,
    ServerEphemeralKey,
    Token,
    TokenHash,
)

config = context.config
target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """Run migrations in offline mode."""
    context.configure(
        url=build_url(DatabaseConfig.get()),
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
