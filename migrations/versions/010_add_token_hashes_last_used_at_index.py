"""Add index on token_hashes.last_used_at

Revision ID: 010
Revises: 009
Create Date: 2026-08-27 00:00:00.000000
"""

from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "010"
down_revision: Union[str, None] = "009"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_index("ix_token_hashes_last_used_at", "token_hashes", ["last_used_at"])


def downgrade() -> None:
    op.drop_index("ix_token_hashes_last_used_at", table_name="token_hashes")
