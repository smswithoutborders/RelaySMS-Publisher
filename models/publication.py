# SPDX-License-Identifier: GPL-3.0-only
"""Publication model and related functions."""

import datetime
from typing import List, Optional

from sqlalchemy import Column, Integer, String, DateTime
from sqlalchemy.orm import Session

from db import Base, get_session


def utc_now() -> datetime.datetime:
    """Get current UTC datetime."""
    return datetime.datetime.now(datetime.timezone.utc)


class Publication(Base):
    """Publication model."""

    __tablename__ = "publications"

    id = Column(Integer, primary_key=True, autoincrement=True)
    country_code = Column(String(10), nullable=True)
    platform_name = Column(String(100), nullable=False)
    source = Column(String(255), nullable=False)
    status = Column(String(50), nullable=False)
    gateway_client = Column(String(255), nullable=True)
    created_at = Column(DateTime, default=utc_now, nullable=False)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now, nullable=False)


def create(
    platform_name: str,
    source: str,
    status: str,
    country_code: Optional[str] = None,
    gateway_client: Optional[str] = None,
    session: Optional[Session] = None,
) -> Publication:
    """Create a new publication."""
    publication = Publication(
        platform_name=platform_name,
        source=source,
        status=status,
        country_code=country_code,
        gateway_client=gateway_client,
    )

    if session:
        session.add(publication)
        session.flush()
        return publication

    with get_session() as s:
        s.add(publication)
        s.flush()
        s.refresh(publication)
        return publication


def get_by_id(
    publication_id: int, session: Optional[Session] = None
) -> Optional[Publication]:
    """Get publication by ID."""
    if session:
        return (
            session.query(Publication).filter(Publication.id == publication_id).first()
        )

    with get_session() as s:
        return s.query(Publication).filter(Publication.id == publication_id).first()


def get_all(
    status: Optional[str] = None,
    platform_name: Optional[str] = None,
    limit: int = 100,
    offset: int = 0,
    session: Optional[Session] = None,
) -> List[Publication]:
    """Get all publications with optional filters."""

    def _query(s: Session):
        query = s.query(Publication)

        if status:
            query = query.filter(Publication.status == status)
        if platform_name:
            query = query.filter(Publication.platform_name == platform_name)

        return query.offset(offset).limit(limit).all()

    if session:
        return _query(session)

    with get_session() as s:
        return _query(s)


def update(
    publication_id: int,
    status: Optional[str] = None,
    country_code: Optional[str] = None,
    gateway_client: Optional[str] = None,
    session: Optional[Session] = None,
) -> Optional[Publication]:
    """Update publication fields."""

    def _update(s: Session):
        publication = (
            s.query(Publication).filter(Publication.id == publication_id).first()
        )
        if not publication:
            return None

        if status is not None:
            publication.status = status
        if country_code is not None:
            publication.country_code = country_code
        if gateway_client is not None:
            publication.gateway_client = gateway_client

        s.flush()
        return publication

    if session:
        return _update(session)

    with get_session() as s:
        return _update(s)


def delete(publication_id: int, session: Optional[Session] = None) -> bool:
    """Delete publication by ID."""

    def _delete(s: Session):
        publication = (
            s.query(Publication).filter(Publication.id == publication_id).first()
        )
        if not publication:
            return False

        s.delete(publication)
        s.flush()
        return True

    if session:
        return _delete(session)

    with get_session() as s:
        return _delete(s)


def count(
    status: Optional[str] = None,
    platform_name: Optional[str] = None,
    session: Optional[Session] = None,
) -> int:
    """Count publications with optional filters."""

    def _count(s: Session):
        query = s.query(Publication)

        if status:
            query = query.filter(Publication.status == status)
        if platform_name:
            query = query.filter(Publication.platform_name == platform_name)

        return query.count()

    if session:
        return _count(session)

    with get_session() as s:
        return _count(s)
