from typing import List, Optional
from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel
from peewee import DoesNotExist
import datetime
from db_models import database, Metrics, init_db

init_db()

app = FastAPI()

class MetricsCreate(BaseModel):
    country_code: str
    platform_name: str
    source: str
    status: str
    gateway_client: str
    date_time: Optional[datetime.datetime] = None
    

class MetricsRead(BaseModel):
    id: int
    country_code: str
    platform_name: str
    source: str
    status: str
    gateway_client: str
    date_time: datetime.datetime
    

@app.post("/metrics/", response_model=MetricsRead, status_code=201)
def create_metric(metric: MetricsCreate):
    """
    Create a new metric entry in the database.
    """
    metric_data = metric.dict()
    if not metric_data.get("date_time"):
        metric_data["date_time"] = datetime.datetime.now()

    new_metric = Metrics.create(**metric_data)
    return MetricsRead(
        id=new_metric.id,
        country_code=new_metric.country_code,
        platform_name=new_metric.platform_name,
        source=new_metric.source,
        status=new_metric.status,
        gateway_client=new_metric.gateway_client,
        date_time=new_metric.date_time,
    )


@app.get("/metrics/", response_model=List[MetricsRead])
def get_metrics(
    start_date: datetime.date = Query(..., description="The start date (required)"),
    end_date: datetime.date = Query(..., description="The end date (required)"),
    country_code: Optional[str] = Query(None),
    platform_name: Optional[str] = Query(None),
    source: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    gateway_client: Optional[str] = Query(None),
):
    """
    Retrieve metrics with optional filters.
    """
    query = Metrics.select()
    
    # Adjust the end_date to include the full day
    start_datetime = datetime.datetime.combine(start_date, datetime.time.min)
    end_datetime = datetime.datetime.combine(end_date, datetime.time.max)

     # Apply required date filters
    query = query.where(Metrics.date_time >= start_datetime)
    query = query.where(Metrics.date_time <= end_datetime)


    # Apply optional filters if provided
    if country_code:
        query = query.where(Metrics.country_code == country_code)
    if platform_name:
        query = query.where(Metrics.platform_name == platform_name)
    if source:
        query = query.where(Metrics.source == source)
    if status:
        query = query.where(Metrics.status == status)
    if gateway_client:
        query = query.where(Metrics.gateway_client == gateway_client)
        
        
    # Fetch and return results
    metrics = list(query)
    return [
        MetricsRead(
            id=metric.id,
            country_code=metric.country_code,
            platform_name=metric.platform_name,
            source=metric.source,
            status=metric.status,
            gateway_client=metric.gateway_client,
            date_time=metric.date_time,
        )
        for metric in metrics
    ]


@app.get("/metrics/{metric_id}", response_model=MetricsRead)
def get_metric_by_id(metric_id: int):
    """
    Retrieve a single metric by its ID.
    """
    try:
        metric = Metrics.get(Metrics.id == metric_id)
        return MetricsRead(
            id=metric.id,
            country_code=metric.country_code,
            platform_name=metric.platform_name,
            source=metric.source,
            status=metric.status,
            gateway_client=metric.gateway_client,
            date_time=metric.date_time,
        )
    except DoesNotExist:
        raise HTTPException(status_code=404, detail="Metric not found")