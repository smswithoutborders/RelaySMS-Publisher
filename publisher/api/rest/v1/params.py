# SPDX-License-Identifier: GPL-3.0-only

import datetime
import hashlib

from fastapi import HTTPException, Query, Request

from publisher.api.rest.v1.errors import ApiError
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


def etag(row_id: object, version: int) -> str:
    digest = hashlib.sha256(f"{row_id}:{version}".encode())
    return f'"{digest.hexdigest()[:32]}"'


def check_if_match(request: Request, current: str, what: str) -> None:
    """Raise 428 without If-Match, or 412 when it isn't the current ETag."""
    if_match = request.headers.get("If-Match")
    if if_match is None:
        raise ApiError(428, "If-Match header required.")
    if if_match.strip() != current:
        raise ApiError(
            412,
            f"This {what} has changed since you loaded it. Reload and try again.",
            log=f"{what}: If-Match {if_match} != ETag {current}",
        )
