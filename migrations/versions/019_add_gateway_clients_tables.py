"""Add gateway_clients, importing the JSON registry

Revision ID: 019
Revises: 018
Create Date: 2026-10-07 00:00:00.000000
"""

import datetime
import json
import logging
import os
import uuid
from collections.abc import Sequence
from pathlib import Path

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "019"
down_revision: str | None = "018"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parents[2]
_FIELDS = ("msisdn", "country", "operator", "operator_code", "protocols")


def _registry_file() -> Path:
    # Only .env files from before this migration set it.
    return ROOT / os.environ.get(
        "GATEWAY_CLIENTS_REGISTRY_FILE", "data/gateway_clients/registry.json"
    )


def _read(path: Path) -> list[dict]:
    if not path.is_file():
        return []
    data = json.loads(path.read_text(encoding="utf-8") or "[]")
    return list(data.values()) if isinstance(data, dict) else data


def _complete(record: dict, path: Path) -> bool:
    if all(record.get(field) for field in _FIELDS):
        return True
    logger.warning("Skipping an incomplete entry in %s: %s", path, record)
    return False


def _import(clients: sa.Table) -> None:
    now = datetime.datetime.now(datetime.UTC).replace(tzinfo=None)
    registry = _registry_file()
    op.bulk_insert(
        clients,
        [
            {
                "id": uuid.uuid4(),
                **{field: record[field] for field in _FIELDS},
                "is_enabled": True,
                "version": 1,
                "created_at": now,
                "updated_at": now,
            }
            for record in _read(registry)
            if _complete(record, registry)
        ],
    )
    overrides = registry.parent / "mcc_mnc_overrides.json"
    for record in _read(overrides):
        logger.warning("MCC/MNC overrides are no longer used; not imported: %s", record)


def upgrade() -> None:
    clients = op.create_table(
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
    _import(clients)


def downgrade() -> None:
    op.drop_table("gateway_clients")
