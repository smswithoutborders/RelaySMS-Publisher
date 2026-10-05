# SPDX-License-Identifier: GPL-3.0-only
"""Credential tables and the scopes a credential can hold."""

import datetime
import uuid
from enum import StrEnum
from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey, Index, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from publisher.db import Base
from publisher.db.types import UTCDateTime, utc_now

if TYPE_CHECKING:
    from publisher.models import CredentialSession

MAX_USERNAME_LENGTH = 32


class Scope(StrEnum):
    STATS_PUBLICATIONS_READ = "stats:publications:read"
    STATS_PUBLICATIONS_REASONS = "stats:publications:reasons"
    GC_READ = "gc:read"
    GC_WRITE = "gc:write"
    PLATFORMS_READ = "platforms:read"
    PLATFORMS_WRITE = "platforms:write"
    CREDS_READ = "creds:read"
    CREDS_WRITE = "creds:write"


ALL_SCOPES = frozenset(Scope)

SCOPE_DESCRIPTIONS = {
    Scope.STATS_PUBLICATIONS_READ: "Read publication stats, without failure reasons",
    Scope.STATS_PUBLICATIONS_REASONS: "See failure reasons in publication stats",
    Scope.GC_READ: "List gateway clients",
    Scope.GC_WRITE: "Add, change and remove gateway clients",
    Scope.PLATFORMS_READ: "List platform adapters",
    Scope.PLATFORMS_WRITE: "Change and remove platform adapters",
    Scope.CREDS_READ: "List credentials",
    Scope.CREDS_WRITE: "Add, change and remove credentials",
}


class CredentialScope(Base):
    __tablename__ = "credential_scopes"

    credential_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("credentials.id", ondelete="CASCADE"), primary_key=True
    )
    scope: Mapped[str] = mapped_column(String(64), primary_key=True)


class Credential(Base):
    __tablename__ = "credentials"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    username: Mapped[str] = mapped_column(String(MAX_USERNAME_LENGTH))
    password_hash: Mapped[str] = mapped_column(String(255))
    is_active: Mapped[bool] = mapped_column(default=True)
    created_at: Mapped[datetime.datetime] = mapped_column(UTCDateTime, default=utc_now)
    updated_at: Mapped[datetime.datetime] = mapped_column(
        UTCDateTime, default=utc_now, onupdate=utc_now
    )
    last_login_at: Mapped[datetime.datetime | None] = mapped_column(
        UTCDateTime, default=None
    )
    # Bumped on every change to detect concurrent changes.
    version: Mapped[int] = mapped_column(default=1)
    # Bumping this ends every session of the credential.
    session_version: Mapped[int] = mapped_column(default=1)

    sessions: Mapped[list["CredentialSession"]] = relationship(
        "CredentialSession", back_populates="credential", cascade="all, delete-orphan"
    )
    scope_rows: Mapped[list[CredentialScope]] = relationship(
        CredentialScope, cascade="all, delete-orphan", lazy="selectin"
    )

    __table_args__ = (Index("uq_credentials_username", "username", unique=True),)

    @property
    def scopes(self) -> frozenset[Scope]:
        return frozenset(
            Scope(row.scope) for row in self.scope_rows if row.scope in ALL_SCOPES
        )

    @property
    def is_administrator(self) -> bool:
        return self.scopes >= ALL_SCOPES
