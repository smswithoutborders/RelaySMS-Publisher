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

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

def create_publication_entry(country_code, platform_name, source, gateway_client, status, date_time=None):
    """
    Store a new publication entry with correct status.

    Args:
        country_code (str): Country code.
        platform_name (str): Platform name.
        source (str): Source of publication.
        gateway_client (str): Gateway client.
        status (str): "published" if successful, "failed" if not.
        date_time (datetime, optional): Timestamp. Defaults to now.
    """
    publication = Publications.create(
        country_code=country_code,
        platform_name=platform_name,
        source=source,
        status=status,
        gateway_client=gateway_client,
        date_time=date_time or datetime.datetime.now()
    )

    log_func = logging.info if status == "published" else logging.error
    log_func("Stored publication: %s", publication.__data__)
            
    return publication

def fetch_publication(start_date: datetime.date, end_date: datetime.date, filters: dict[str, Optional[str]]) -> dict[str, any]:
    """Fetch publications based on filters."""
    query = Publications.select().where(
        (Publications.date_time >= start_date) & (Publications.date_time <= end_date)
    )
    
    for key, value in filters.items():
        if value:
            query = query.where(getattr(Publications, key) == value)
            
    total_publications = query.count()
    total_published = query.where(Publications.status == "published").count()
    total_failed = query.where(Publications.status == "failed").count()

    return {
        "data": list(query),
        "total_publications": total_publications,
        "total_published": total_published,
        "total_failed": total_failed,
    }
    