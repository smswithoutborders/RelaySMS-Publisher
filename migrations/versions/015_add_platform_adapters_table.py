"""Add platform_adapters, replacing the JSON registry

Revision ID: 015
Revises: 014
Create Date: 2026-10-06 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "015"
down_revision: str | None = "014"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "platform_adapters",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("source_url", sa.String(length=255), nullable=False),
        sa.Column("commit", sa.String(length=40), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("display_name", sa.String(length=100), nullable=False),
        sa.Column("proto_id", sa.SmallInteger(), nullable=False),
        sa.Column("cat_id", sa.SmallInteger(), nullable=False),
        sa.Column("auth_provider", sa.String(length=100), nullable=True),
        sa.Column("supports_offline_first", sa.Boolean(), nullable=False),
        sa.Column("icon_svg", sa.Text(), nullable=True),
        sa.Column("icon_png", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("updated_by", sa.Uuid(), nullable=True),
    )
    op.create_index(
        "uq_platform_adapters_name_proto_id",
        "platform_adapters",
        ["name", "proto_id"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_table("platform_adapters")
