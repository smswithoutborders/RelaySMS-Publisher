"""Rename publications table to publication_stats and adjust columns

Revision ID: 009
Revises: 008
Create Date: 2026-08-07 00:00:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "009"
down_revision: Union[str, None] = "008"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.rename_table("publications", "publication_stats")

    with op.batch_alter_table("publication_stats") as batch_op:
        batch_op.drop_column("source")
        batch_op.drop_column("gateway_client")
        batch_op.drop_column("updated_at")
        batch_op.add_column(sa.Column("protocol", sa.String(length=20), nullable=True))
        batch_op.add_column(
            sa.Column("failure_reason", sa.String(length=255), nullable=True)
        )
        batch_op.alter_column(
            "platform_name", existing_type=sa.String(length=100), nullable=True
        )
        batch_op.alter_column(
            "status", existing_type=sa.String(length=50), type_=sa.String(length=20)
        )

    op.create_index(
        "ix_publication_stats_created_at", "publication_stats", ["created_at"]
    )
    op.create_index(
        "ix_publication_stats_status_created_at",
        "publication_stats",
        ["status", "created_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_publication_stats_status_created_at", table_name="publication_stats"
    )
    op.drop_index("ix_publication_stats_created_at", table_name="publication_stats")

    with op.batch_alter_table("publication_stats") as batch_op:
        batch_op.drop_column("failure_reason")
        batch_op.drop_column("protocol")
        batch_op.alter_column(
            "status", existing_type=sa.String(length=20), type_=sa.String(length=50)
        )
        batch_op.add_column(sa.Column("updated_at", sa.DateTime(), nullable=True))
        batch_op.add_column(
            sa.Column("gateway_client", sa.String(length=255), nullable=True)
        )
        batch_op.add_column(sa.Column("source", sa.String(length=255), nullable=True))

    # Re-adding these columns as NOT NULL directly would fail on a non-empty
    # table (no default to satisfy existing rows), so backfill first.
    publication_stats = sa.table(
        "publication_stats",
        sa.column("platform_name", sa.String),
        sa.column("updated_at", sa.DateTime),
        sa.column("created_at", sa.DateTime),
        sa.column("source", sa.String),
    )
    op.execute(
        publication_stats.update()
        .values(platform_name="unknown")
        .where(publication_stats.c.platform_name.is_(None))
    )
    op.execute(
        publication_stats.update().values(updated_at=publication_stats.c.created_at)
    )
    op.execute(publication_stats.update().values(source="platforms"))

    with op.batch_alter_table("publication_stats") as batch_op:
        batch_op.alter_column(
            "platform_name", existing_type=sa.String(length=100), nullable=False
        )
        batch_op.alter_column("updated_at", existing_type=sa.DateTime(), nullable=False)
        batch_op.alter_column(
            "source", existing_type=sa.String(length=255), nullable=False
        )

    op.rename_table("publication_stats", "publications")
