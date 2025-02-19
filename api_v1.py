"""
This program is free software: you can redistribute it under the terms
of the GNU General Public License, v. 3.0. If a copy of the GNU General
Public License was not distributed with this file, see <https://www.gnu.org/licenses/>.
"""

from fastapi import APIRouter, HTTPException, Query
from typing import List, Optional
import datetime
import logging
from api_schemas import PublicationsRead, PublicationsResponse, Pagination
from publications import fetch_publication

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/metrics/publications", response_model=PublicationsResponse)
def get_publication(
    start_date: datetime.date = Query(...),
    end_date: datetime.date = Query(...),
    country_code: Optional[str] = Query(None),
    platform_name: Optional[str] = Query(None),
    source: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    gateway_client: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(10, ge=1, le=100),
):
    """Retrieve metrics with optional filters."""
    logger.info(
        f"Fetching metrics with filters: start_date={start_date}, end_date={end_date}, "
        f"country_code={country_code}, platform_name={platform_name}, source={source}, "
        f"status={status}, gateway_client={gateway_client}, page={page}, page_size={page_size}"
    )

    filters = {
        "country_code": country_code,
        "platform_name": platform_name,
        "source": source,
        "status": status,
        "gateway_client": gateway_client,
    }

    try:
        result = fetch_publication(start_date, end_date, filters, page, page_size)
        publications = [
            PublicationsRead(**publication.__data__) for publication in result["data"]
        ]
        total_records = result.get("total_publications", 0)
        total_pages = (total_records + page_size - 1) // page_size

        return PublicationsResponse(
            total_publications=result.get("total_publications", 0),
            total_published=result.get("total_published", 0),
            total_failed=result.get("total_failed", 0),
            data=publications,
             pagination=Pagination(
                total_records=total_records,
                page=page,
                page_size=page_size,
                total_pages=total_pages,
            ),
        )

    except Exception as e:
        logger.error(f"Error fetching publications: {e}")
        raise HTTPException(status_code=500, detail="Error fetching publications")
