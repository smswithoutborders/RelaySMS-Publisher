"""Add client ephemeral keys table

Revision ID: 005
Revises: 004
Create Date: 2026-06-03 00:00:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "005"
down_revision: Union[str, None] = "004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade():
    op.create_table(
        "client_ephemeral_keys",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "token_hash_id",
            sa.Integer(),
            sa.ForeignKey("token_hashes.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("key_index", sa.Integer(), nullable=False),
        sa.Column("public_key", sa.LargeBinary(length=32), nullable=False),
        sa.Column("used", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("used_at", sa.DateTime(), nullable=True),
        sa.UniqueConstraint(
            "token_hash_id", "key_index", name="uq_client_keys_token_hash_id_key_index"
        ),
    )
    op.create_index(
        "ix_client_ephemeral_keys_token_hash_id_used",
        "client_ephemeral_keys",
        ["token_hash_id", "used"],
    )


def downgrade():
    op.drop_index(
        "ix_client_ephemeral_keys_token_hash_id_used",
        table_name="client_ephemeral_keys",
    )
    op.drop_table("client_ephemeral_keys")
