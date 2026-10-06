# SPDX-License-Identifier: GPL-3.0-only
"""Installed platform adapters."""

import datetime
import uuid

from sqlalchemy import Index, SmallInteger, String, Text, Uuid, select
from sqlalchemy.orm import Mapped, Session, mapped_column

from publisher.config import PlatformsConfig
from publisher.db import Base
from publisher.db.types import UTCDateTime, utc_now

OAUTH2 = 0
PNBA = 1


class PlatformAdapter(Base):
    __tablename__ = "platform_adapters"

    # uuid5 of the source URL, which also names the adapter's directories.
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    source_url: Mapped[str] = mapped_column(String(255))
    commit: Mapped[str] = mapped_column(String(40))
    name: Mapped[str] = mapped_column(String(100))
    display_name: Mapped[str] = mapped_column(String(100))
    proto_id: Mapped[int] = mapped_column(SmallInteger)
    cat_id: Mapped[int] = mapped_column(SmallInteger)
    auth_provider: Mapped[str | None] = mapped_column(String(100), default=None)
    supports_offline_first: Mapped[bool] = mapped_column(default=False)
    icon_svg: Mapped[str | None] = mapped_column(Text, default=None)
    icon_png: Mapped[str | None] = mapped_column(Text, default=None)
    created_at: Mapped[datetime.datetime] = mapped_column(UTCDateTime, default=utc_now)
    # The *_by columns are NULL when the CLI made the change.
    created_by: Mapped[uuid.UUID | None] = mapped_column(Uuid, default=None)
    updated_at: Mapped[datetime.datetime] = mapped_column(
        UTCDateTime, default=utc_now, onupdate=utc_now
    )
    updated_by: Mapped[uuid.UUID | None] = mapped_column(Uuid, default=None)

    __table_args__ = (
        Index("uq_platform_adapters_name_proto_id", "name", "proto_id", unique=True),
    )

    # Paths come from config, so moving the data directory needs no rewrite.
    @property
    def path(self) -> str:
        return str(PlatformsConfig.get().adapters_dir / self.id)

    @property
    def venv_path(self) -> str:
        return str(PlatformsConfig.get().adapters_venv_dir / self.id)

    @property
    def assets_path(self) -> str:
        return str(PlatformsConfig.get().adapters_assets_dir / self.id)


def find(
    session: Session,
    *,
    name: str | None = None,
    proto_id: int | None = None,
    cat_id: int | None = None,
) -> list[PlatformAdapter]:
    stmt = select(PlatformAdapter).order_by(
        PlatformAdapter.name, PlatformAdapter.proto_id
    )
    if name is not None:
        stmt = stmt.where(PlatformAdapter.name == name.strip().lower())
    if proto_id is not None:
        stmt = stmt.where(PlatformAdapter.proto_id == proto_id)
    if cat_id is not None:
        stmt = stmt.where(PlatformAdapter.cat_id == cat_id)
    return list(session.scalars(stmt))


def get_for_protocol(session: Session, platform: str, proto_id: int) -> PlatformAdapter:
    """Raises NotImplementedError when no adapter serves platform over proto_id."""
    adapters = find(session, name=platform, proto_id=proto_id)
    if not adapters:
        protocol = {OAUTH2: "oauth2", PNBA: "pnba"}[proto_id]
        raise NotImplementedError(
            f"Platform '{platform.lower()}' with protocol '{protocol}' is not "
            "supported. Contact the developers for implementation status."
        )
    return adapters[0]
