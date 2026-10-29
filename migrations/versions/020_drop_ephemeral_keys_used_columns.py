# SPDX-License-Identifier: GPL-3.0-only
"""Drop used and used_at from the ephemeral key tables

Revision ID: 020
Revises: 019
Create Date: 2026-10-29 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "020"
down_revision: str | None = "019"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLES = ("server_ephemeral_keys", "client_ephemeral_keys")


def upgrade() -> None:
    for table in TABLES:
        with op.batch_alter_table(table) as batch:
            batch.drop_index(f"ix_{table}_token_hash_id_used")
            batch.drop_column("used_at")
            batch.drop_column("used")


def downgrade() -> None:
    for table in TABLES:
        with op.batch_alter_table(table) as batch:
            batch.add_column(
                sa.Column(
                    "used", sa.Boolean(), nullable=False, server_default=sa.false()
                )
            )
            batch.add_column(sa.Column("used_at", sa.DateTime(), nullable=True))
            batch.create_index(
                f"ix_{table}_token_hash_id_used", ["token_hash_id", "used"]
            )
