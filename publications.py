"""
This program is free software: you can redistribute it under the terms
of the GNU General Public License, v. 3.0. If a copy of the GNU General
Public License was not distributed with this file, see <https://www.gnu.org/licenses/>.
"""

import datetime
import logging
from db_models import Publications
from peewee import fn
from typing import Optional
from datetime import datetime, timedelta

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


def create_publication_entry(
    platform_name,
    source,
    status,
    country_code=None,
    gateway_client=None,
    date_created=None,
):
    """
    Store a new publication entry with correct status.

    Args:
        country_code (str): Country code.
        platform_name (str): Platform name.
        source (str): Source of publication.
        gateway_client (str): Gateway client.
        status (str): "published" if successful, "failed" if not.
    """
    publication = Publications.create(
        country_code=country_code,
        platform_name=platform_name,
        source=source,
        status=status,
        gateway_client=gateway_client,
    )

    logger.info("Successfully logged publication")

    return publication


def fetch_publication(
    start_date: datetime.date,
    end_date: datetime.date,
    filters: dict[str, Optional[str]],
    page: int = 1,
    page_size: int = 10,
) -> dict[str, any]:
    """Fetch publications based on filters with pagination."""

    start_datetime = datetime.combine(start_date, datetime.min.time())
    end_datetime = datetime.combine(end_date, datetime.max.time())

    query = Publications.select().where(
        (Publications.date_created >= start_datetime)
        & (Publications.date_created <= end_datetime)
    )

    for key, value in filters.items():
        if value:
            query = query.where(getattr(Publications, key) == value)

    total_publications = query.count()
    total_published = query.where(Publications.status == "published").count()
    total_failed = query.where(Publications.status == "failed").count()

    offset = (page - 1) * page_size
    paginated_query = query.limit(page_size).offset(offset)

    return {
        "data": list(paginated_query),
        "total_publications": total_publications,
        "total_published": total_published,
        "total_failed": total_failed,
        "page": page,
        "page_size": page_size,
        "total_pages": (total_publications + page_size - 1) // page_size, 
    }
