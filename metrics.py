"""
This program is free software: you can redistribute it under the terms
of the GNU General Public License, v. 3.0. If a copy of the GNU General
Public License was not distributed with this file, see <https://www.gnu.org/licenses/>.
"""

from peewee import fn
from db_models import Publications

def get_publications(filters=None):
    """Retrieve publication data including total failed and published counts.

    Args:
        filters (dict, optional): A dictionary containing filtering options:
            - start_date (str): Start date for filtering records (YYYY-MM-DD).
            - end_date (str): End date for filtering records (YYYY-MM-DD).
            - country_code (str): Country code to filter results by.

    Returns:
        dict: A dictionary containing publication counts:
            - total_publications (int): Total number of publications.
            - total_published (int): Total number of successfully published records.
            - total_failed (int): Total number of failed publications.
    """
    filters = filters or {}
    start_date = filters.get("start_date")
    end_date = filters.get("end_date")
    country_code = filters.get("country_code")

    query = Publications.select()

    if start_date:
        query = query.where(Publications.date_time >= start_date)
    if end_date:
        query = query.where(Publications.date_time <= end_date)
    if country_code:
        query = query.where(Publications.country_code == country_code)

    total_publications = query.select(fn.COUNT(Publications.id)).scalar()
    total_published = query.select(fn.COUNT(Publications.id)).where(Publications.status == "published").scalar()
    total_failed = query.select(fn.COUNT(Publications.id)).where(Publications.status == "failed").scalar()

    return {
        "total_publications": total_publications,
        "total_published": total_published,
        "total_failed": total_failed,
    }
