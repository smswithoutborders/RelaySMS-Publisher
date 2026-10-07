"""Add platform_adapters.tag and platform_adapter_jobs

Revision ID: 018
Revises: 017
Create Date: 2026-10-06 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "018"
down_revision: str | None = "017"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("platform_adapters") as batch:
        batch.add_column(sa.Column("tag", sa.String(length=100), nullable=True))

    op.create_table(
        "platform_adapter_jobs",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("adapter_id", sa.String(length=36), nullable=False),
        sa.Column("action", sa.String(length=16), nullable=False),
        sa.Column("source_url", sa.String(length=255), nullable=False),
        sa.Column("tag", sa.String(length=100), nullable=True),
        sa.Column("from_commit", sa.String(length=40), nullable=True),
        sa.Column("to_commit", sa.String(length=40), nullable=True),
        sa.Column("state", sa.String(length=16), nullable=False),
        sa.Column("lock", sa.String(length=36), nullable=True),
        sa.Column("log", sa.Text(), nullable=False),
        sa.Column("requested_by", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("finished_at", sa.DateTime(), nullable=True),
    )
    op.create_index(
        "uq_platform_adapter_jobs_lock", "platform_adapter_jobs", ["lock"], unique=True
    )
    op.create_index(
        "ix_platform_adapter_jobs_adapter_id",
        "platform_adapter_jobs",
        ["adapter_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_table("platform_adapter_jobs")
    with op.batch_alter_table("platform_adapters") as batch:
        batch.drop_column("tag")
