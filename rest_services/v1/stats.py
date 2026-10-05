# SPDX-License-Identifier: GPL-3.0-only

import dataclasses
import datetime

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    Query,
    Request,
    Security,
)
from sqlalchemy.orm import Session

from publisher.db import get_db
from publisher.db.types import as_utc, utc_now
from publisher.models import publication_stats
from publisher.models.credential import Scope
from rest_services.v1.auth import AuthContext, authorize, require_scopes
from rest_services.v1.params import filter_query
from rest_services.v1.schemas import (
    PublicationStatsPage,
    PublicationStatsSummary,
    PublicationStatsSummaryGroup,
    StatsGroupBy,
    StatsInterval,
)

router = APIRouter(prefix="/stats", tags=["Stats"])

STATS_SUMMARY_DEFAULT_WINDOW = datetime.timedelta(days=30)


def stats_filters(
    status: str | None = filter_query(20, "Filter by status"),
    platform_name: str | None = filter_query(100, "Filter by platform name"),
    protocol: str | None = filter_query(20, "Filter by ingestion protocol"),
    country_code: str | None = filter_query(10, "Filter by ISO country code"),
    since: datetime.datetime | None = Query(
        None,
        description="Created at or after (ISO-8601, UTC if no offset)",
    ),
    until: datetime.datetime | None = Query(
        None,
        description="Created before (ISO-8601, UTC if no offset)",
    ),
) -> publication_stats.StatsFilters:
    since, until = as_utc(since), as_utc(until)
    if since is not None and until is not None and since >= until:
        raise HTTPException(status_code=400, detail="'since' must be before 'until'.")

    return publication_stats.StatsFilters(
        status=status,
        platform_name=platform_name,
        protocol=protocol,
        country_code=country_code,
        since=since,
        until=until,
    )


def _page_link(request: Request, cursor: str | None) -> str | None:
    return str(request.url.include_query_params(cursor=cursor)) if cursor else None


@router.get(
    "/publications", response_model=PublicationStatsPage, summary="List publications"
)
def list_publication_stats(
    request: Request,
    context: AuthContext = Security(authorize, scopes=[Scope.STATS_PUBLICATIONS_READ]),
    filters: publication_stats.StatsFilters = Depends(stats_filters),
    limit: int = Query(50, ge=1, le=200, description="Page size"),
    cursor: str | None = Query(
        None, max_length=512, description="Set by the next and prev links"
    ),
    db: Session = Depends(get_db),
) -> PublicationStatsPage:
    """Newest first. Scope: stats:publications:read (+ :reasons for failure_reason)."""
    decoded_cursor = publication_stats.decode_cursor(cursor) if cursor else None

    page = publication_stats.list_stats(
        db, filters=filters, limit=limit, cursor=decoded_cursor
    )
    result = PublicationStatsPage.model_validate(
        {
            "data": page.data,
            "next": _page_link(request, page.next_cursor),
            "prev": _page_link(request, page.prev_cursor),
        }
    )
    if Scope.STATS_PUBLICATIONS_REASONS not in context.credential.scopes:
        for item in result.data:
            item.failure_reason = None
    return result


@router.get(
    "/publications/summary",
    response_model=PublicationStatsSummary,
    summary="Summarize publications",
)
def summarize_publication_stats(
    context: AuthContext = Security(authorize, scopes=[Scope.STATS_PUBLICATIONS_READ]),
    filters: publication_stats.StatsFilters = Depends(stats_filters),
    group_by: list[StatsGroupBy] = Query(
        [StatsGroupBy.status],
        description="Columns to group by. Repeatable.",
    ),
    interval: StatsInterval | None = Query(
        None, description="Also group by period start, in UTC. Weeks start Monday."
    ),
    db: Session = Depends(get_db),
) -> PublicationStatsSummary:
    """Counts per group; last 30 days by default. Scope: stats:publications:read."""
    columns = list(dict.fromkeys(item.value for item in group_by))
    if "failure_reason" in columns:
        require_scopes(context, Scope.STATS_PUBLICATIONS_REASONS)
    unit = interval.value if interval else None
    until = filters.until or utc_now()
    since = filters.since or until - STATS_SUMMARY_DEFAULT_WINDOW
    if since >= until:
        raise HTTPException(status_code=400, detail="'since' must be before 'until'.")

    groups = publication_stats.summarize(
        db,
        group_by=columns,
        filters=dataclasses.replace(filters, since=since, until=until),
        interval=unit,
    )
    return PublicationStatsSummary(
        since=since,
        until=until,
        interval=interval,
        total=sum(group["count"] for group in groups),
        groups=[PublicationStatsSummaryGroup.model_validate(g) for g in groups],
    )
