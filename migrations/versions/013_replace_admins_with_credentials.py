"""Replace admin_users and admin_sessions with scoped credentials

Revision ID: 013
Revises: 012
Create Date: 2026-10-01 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "013"
down_revision: str | None = "012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_table("admin_sessions")
    op.drop_table("admin_users")

    op.create_table(
        "credentials",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("username", sa.String(length=32), nullable=False),
        sa.Column("password_hash", sa.String(length=255), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("last_login_at", sa.DateTime(), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("session_version", sa.Integer(), nullable=False),
    )
    op.create_index("uq_credentials_username", "credentials", ["username"], unique=True)

    op.create_table(
        "credential_scopes",
        sa.Column(
            "credential_id",
            sa.Uuid(),
            sa.ForeignKey("credentials.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("scope", sa.String(length=64), primary_key=True),
    )

    op.create_table(
        "credential_sessions",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "credential_id",
            sa.Uuid(),
            sa.ForeignKey("credentials.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("session_version", sa.Integer(), nullable=False),
        sa.Column("user_agent", sa.String(length=255), nullable=True),
    )
    op.create_index(
        "uq_credential_sessions_token_hash",
        "credential_sessions",
        ["token_hash"],
        unique=True,
    )
    op.create_index(
        "ix_credential_sessions_credential_id",
        "credential_sessions",
        ["credential_id"],
    )
    op.create_index(
        "ix_credential_sessions_expires_at", "credential_sessions", ["expires_at"]
    )


def downgrade() -> None:
    op.drop_table("credential_sessions")
    op.drop_table("credential_scopes")
    op.drop_table("credentials")

    op.create_table(
        "admin_users",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("email", sa.String(length=254), nullable=False),
        sa.Column("password_hash", sa.String(length=255), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("last_login_at", sa.DateTime(), nullable=True),
    )
    op.create_index("uq_admin_users_email", "admin_users", ["email"], unique=True)

    op.create_table(
        "admin_sessions",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "admin_user_id",
            sa.Integer(),
            sa.ForeignKey("admin_users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("user_agent", sa.String(length=255), nullable=True),
    )
    op.create_index(
        "uq_admin_sessions_token_hash", "admin_sessions", ["token_hash"], unique=True
    )
    op.create_index(
        "ix_admin_sessions_admin_user_id", "admin_sessions", ["admin_user_id"]
    )
    op.create_index("ix_admin_sessions_expires_at", "admin_sessions", ["expires_at"])
