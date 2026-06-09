# SPDX-License-Identifier: GPL-3.0-only
"""Publication model and related functions."""

import datetime

from sqlalchemy import Column, DateTime, Integer, String

from db import Base


def utc_now() -> datetime.datetime:
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
