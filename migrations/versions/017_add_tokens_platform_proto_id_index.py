"""Add an index on tokens (platform, proto_id)

Revision ID: 017
Revises: 016
Create Date: 2026-10-06 00:00:00.000000
"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "017"
down_revision: str | None = "016"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_index("ix_tokens_platform_proto_id", "tokens", ["platform", "proto_id"])


def downgrade() -> None:
    op.drop_index("ix_tokens_platform_proto_id", table_name="tokens")
