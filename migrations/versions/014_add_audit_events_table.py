"""Add audit_events and grant audit:read to administrators

Revision ID: 014
Revises: 013
Create Date: 2026-10-06 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "014"
down_revision: str | None = "013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Every scope before audit:read; holders were administrators and should stay so.
_PREVIOUS_SCOPES = (
    "stats:publications:read",
    "stats:publications:reasons",
    "gc:read",
    "gc:write",
    "platforms:read",
    "platforms:write",
    "creds:read",
    "creds:write",
)


def upgrade() -> None:
    op.create_table(
        "audit_events",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("occurred_at", sa.DateTime(), nullable=False),
        sa.Column("actor_id", sa.Uuid(), nullable=True),
        sa.Column("actor_username", sa.String(length=32), nullable=True),
        sa.Column("action", sa.String(length=64), nullable=False),
        sa.Column("target_id", sa.String(length=64), nullable=True),
        sa.Column("target_label", sa.String(length=255), nullable=True),
        sa.Column("outcome", sa.String(length=16), nullable=False),
        sa.Column("details", sa.JSON(), nullable=True),
    )
    op.create_index(
        "ix_audit_events_occurred_at_id", "audit_events", ["occurred_at", "id"]
    )

    scopes = sa.table(
        "credential_scopes",
        sa.column("credential_id", sa.Uuid()),
        sa.column("scope", sa.String()),
    )
    administrators = (
        sa.select(scopes.c.credential_id)
        .where(scopes.c.scope.in_(_PREVIOUS_SCOPES))
        .group_by(scopes.c.credential_id)
        .having(sa.func.count() == len(_PREVIOUS_SCOPES))
    )
    op.execute(
        scopes.insert().from_select(
            ["credential_id", "scope"],
            sa.select(
                administrators.subquery().c.credential_id,
                sa.literal("audit:read"),
            ),
        )
    )


def downgrade() -> None:
    op.execute("DELETE FROM credential_scopes WHERE scope = 'audit:read'")
    op.drop_table("audit_events")
