"""Add is_enabled and version to platform_adapters

Revision ID: 016
Revises: 015
Create Date: 2026-10-06 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "016"
down_revision: str | None = "015"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("platform_adapters") as batch:
        batch.add_column(
            sa.Column(
                "is_enabled", sa.Boolean(), nullable=False, server_default=sa.true()
            )
        )
        batch.add_column(
            sa.Column("version", sa.Integer(), nullable=False, server_default="1")
        )


def downgrade() -> None:
    with op.batch_alter_table("platform_adapters") as batch:
        batch.drop_column("version")
        batch.drop_column("is_enabled")
