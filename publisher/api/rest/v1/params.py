# SPDX-License-Identifier: GPL-3.0-only

import datetime

from fastapi import HTTPException, Query, Request

from publisher.db.types import as_utc

NAME_PATTERN = r"^[a-zA-Z0-9_-]+$"


def filter_query(max_length: int, description: str):
    return Query(
        None,
        max_length=max_length,
        pattern=NAME_PATTERN,
        description=description,
    )


def page_link(request: Request, cursor: str | None) -> str | None:
    return str(request.url.include_query_params(cursor=cursor)) if cursor else None


def check_time_range(
    since: datetime.datetime | None, until: datetime.datetime | None
) -> tuple[datetime.datetime | None, datetime.datetime | None]:
    """Return both in UTC, or raise 400 if since isn't before until."""
    since, until = as_utc(since), as_utc(until)
    if since is not None and until is not None and since >= until:
        raise HTTPException(status_code=400, detail="'since' must be before 'until'.")
    return since, until
