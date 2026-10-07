# SPDX-License-Identifier: GPL-3.0-only
"""Gateway clients: the phone numbers that relay SMS to this server."""

import datetime
import uuid
from typing import ClassVar

from sqlalchemy import JSON, Index, String, Uuid, select
from sqlalchemy.orm import Mapped, Session, mapped_column

from publisher.db import Base
from publisher.db.types import UTCDateTime, utc_now


class GatewayClient(Base):
    __tablename__ = "gateway_clients"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    msisdn: Mapped[str] = mapped_column(String(20))
    country: Mapped[str] = mapped_column(String(100))
    operator: Mapped[str] = mapped_column(String(100))
    # PLMN: MCC + MNC.
    operator_code: Mapped[str] = mapped_column(String(6))
    protocols: Mapped[list[str]] = mapped_column(JSON)
    is_enabled: Mapped[bool] = mapped_column(default=True)
    version: Mapped[int] = mapped_column(default=1)
    created_at: Mapped[datetime.datetime] = mapped_column(UTCDateTime, default=utc_now)
    # The *_by columns are NULL when the CLI made the change.
    created_by: Mapped[uuid.UUID | None] = mapped_column(Uuid, default=None)
    updated_at: Mapped[datetime.datetime] = mapped_column(
        UTCDateTime, default=utc_now, onupdate=utc_now
    )
    updated_by: Mapped[uuid.UUID | None] = mapped_column(Uuid, default=None)

    __table_args__ = (Index("uq_gateway_clients_msisdn", "msisdn", unique=True),)
    __mapper_args__: ClassVar[dict] = {"version_id_col": version}


def find(
    session: Session,
    *,
    msisdn: str | None = None,
    country: str | None = None,
    operator: str | None = None,
    include_disabled: bool = False,
) -> list[GatewayClient]:
    """Enabled only, unless include_disabled. Country and operator ignore case."""
    stmt = select(GatewayClient).order_by(
        GatewayClient.country, GatewayClient.operator, GatewayClient.msisdn
    )
    if msisdn is not None:
        stmt = stmt.where(GatewayClient.msisdn == msisdn.strip())
    if not include_disabled:
        stmt = stmt.where(GatewayClient.is_enabled)
    # Filtered here: SQLite's lower() only folds ASCII.
    country, operator = (
        term.strip().casefold() if term else None for term in (country, operator)
    )
    return [
        client
        for client in session.scalars(stmt)
        if (country is None or client.country.casefold() == country)
        and (operator is None or client.operator.casefold() == operator)
    ]


def get_by_msisdn(session: Session, msisdn: str) -> GatewayClient | None:
    return session.scalar(
        select(GatewayClient).where(GatewayClient.msisdn == msisdn.strip())
    )
