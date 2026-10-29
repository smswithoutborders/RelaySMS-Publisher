"""Add gateway_clients

Revision ID: 019
Revises: 018
Create Date: 2026-10-07 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "019"
down_revision: str | None = "018"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "gateway_clients",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("msisdn", sa.String(length=20), nullable=False),
        sa.Column("country", sa.String(length=100), nullable=False),
        sa.Column("operator", sa.String(length=100), nullable=False),
        sa.Column("operator_code", sa.String(length=6), nullable=False),
        sa.Column("protocols", sa.JSON(), nullable=False),
        sa.Column("is_enabled", sa.Boolean(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("updated_by", sa.Uuid(), nullable=True),
    )
    op.create_index(
        "uq_gateway_clients_msisdn", "gateway_clients", ["msisdn"], unique=True
    )


def downgrade() -> None:
    op.drop_table("gateway_clients")
