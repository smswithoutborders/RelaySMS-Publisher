"""Add tokens table

Revision ID: 002
Revises: 001
Create Date: 2026-06-03 00:00:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "002"
down_revision: Union[str, None] = "001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "tokens",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("token_id", sa.BigInteger(), nullable=False, unique=True),
        sa.Column("platform", sa.String(length=100), nullable=False),
        sa.Column("cat_id", sa.SmallInteger(), nullable=False),
        sa.Column("proto_id", sa.SmallInteger(), nullable=False),
        sa.Column("token_data", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("tokens")
