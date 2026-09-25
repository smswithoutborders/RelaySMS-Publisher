"""Add keyset pagination and platform/country filter indexes on publication_stats

Revision ID: 011
Revises: 010
Create Date: 2026-09-24 00:00:00.000000
"""

from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "011"
down_revision: Union[str, None] = "010"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # (created_at, id) supersedes the single-column created_at index.
    op.create_index(
        "ix_publication_stats_created_at_id",
        "publication_stats",
        ["created_at", "id"],
    )
    op.drop_index("ix_publication_stats_created_at", table_name="publication_stats")
    op.create_index(
        "ix_publication_stats_platform_name_created_at",
        "publication_stats",
        ["platform_name", "created_at"],
    )
    op.create_index(
        "ix_publication_stats_country_code_created_at",
        "publication_stats",
        ["country_code", "created_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_publication_stats_country_code_created_at",
        table_name="publication_stats",
    )
    op.drop_index(
        "ix_publication_stats_platform_name_created_at",
        table_name="publication_stats",
    )
    op.create_index(
        "ix_publication_stats_created_at", "publication_stats", ["created_at"]
    )
    op.drop_index("ix_publication_stats_created_at_id", table_name="publication_stats")
