# SPDX-License-Identifier: GPL-3.0-only
"""Add publication_stats.trace_id with an index

Revision ID: 021
Revises: 020
Create Date: 2026-11-24 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "021"
down_revision: str | None = "020"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("publication_stats") as batch:
        batch.add_column(sa.Column("trace_id", sa.String(32), nullable=True))
        batch.create_index("ix_publication_stats_trace_id", ["trace_id"])


def downgrade() -> None:
    with op.batch_alter_table("publication_stats") as batch:
        batch.drop_index("ix_publication_stats_trace_id")
        batch.drop_column("trace_id")
