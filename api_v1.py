from fastapi import FastAPI, HTTPException, Query, APIRouter
from typing import List, Optional
import datetime
from pydantic import BaseModel
from publications import create_publication_entry, get_publication
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

router = APIRouter()

class PublicationsCreate(BaseModel):
    country_code: str
    platform_name: str
    source: str
    status: str
    gateway_client: str
    date_time: Optional[datetime.datetime] = None

class PublicationsRead(PublicationsCreate):
    id: int

@router.get("/metrics/publications", response_model=List[PublicationsRead])
def fetch_publication(
    start_date: datetime.date = Query(...),
    end_date: datetime.date = Query(...),
    country_code: Optional[str] = Query(None),
    platform_name: Optional[str] = Query(None),
    source: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    gateway_client: Optional[str] = Query(None),
):
    """Retrieve metrics with optional filters."""
    logger.info(f"Fetching metrics with filters: start_date={start_date}, end_date={end_date}, "
                f"country_code={country_code}, platform_name={platform_name}, source={source}, "
                f"status={status}, gateway_client={gateway_client}")
    filters = {
        "country_code": country_code,
        "platform_name": platform_name,
        "source": source,
        "status": status,
        "gateway_client": gateway_client,
    }
    try:
        publications = get_publication(start_date, end_date, filters)
        logger.info(f"Found {len(publications)} publications.")
        return [PublicationsRead(**publication.__data__) for publication in publications]
    except Exception as e:
        logger.error(f"Error fetching publications: {e}")
        raise HTTPException(status_code=500, detail="Error fetching publications")

app = FastAPI()

app.include_router(router, prefix="/v1")