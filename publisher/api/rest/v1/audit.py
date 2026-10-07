# SPDX-License-Identifier: GPL-3.0-only
"""The audit log of credential activity."""

import datetime

from fastapi import APIRouter, Depends, Query, Request, Security
from sqlalchemy.orm import Session

from publisher.api.rest.v1.auth import AuthContext, authorize
from publisher.api.rest.v1.errors import PAGE_QUERY_ERRORS, error_responses
from publisher.api.rest.v1.params import check_time_range, page_link
from publisher.api.rest.v1.schemas import AuditEventInfo, AuditEventPage
from publisher.db import get_db, pagination
from publisher.models import audit_event
from publisher.models.audit_event import AuditAction
from publisher.models.credential import MAX_USERNAME_LENGTH, Scope

router = APIRouter(prefix="/audit-events", tags=["Audit"])


@router.get(
    "",
    response_model=AuditEventPage,
    summary="List audit events",
    responses=error_responses(PAGE_QUERY_ERRORS),
)
def list_audit_events(
    request: Request,
    context: AuthContext = Security(authorize, scopes=[Scope.AUDIT_READ]),
    action: AuditAction | None = Query(None, description="Filter by action"),
    actor: str | None = Query(
        None, max_length=MAX_USERNAME_LENGTH, description="Filter by actor username"
    ),
    target: str | None = Query(
        None, max_length=255, description="Filter by target name"
    ),
    since: datetime.datetime | None = Query(
        None, description="At or after (ISO-8601, UTC if no offset)"
    ),
    until: datetime.datetime | None = Query(
        None, description="Before (ISO-8601, UTC if no offset)"
    ),
    limit: int = Query(50, ge=1, le=200, description="Page size"),
    cursor: str | None = Query(
        None, max_length=512, description="Set by the next and prev links"
    ),
    db: Session = Depends(get_db),
) -> AuditEventPage:
    """Newest first. Scope: audit:read, plus creds:read or platforms:read per area."""
    since, until = check_time_range(since, until)
    page = audit_event.list_events(
        db,
        scopes=context.credential.scopes,
        limit=limit,
        cursor=pagination.decode_cursor(cursor) if cursor else None,
        action=action,
        actor=actor,
        target=target,
        since=since,
        until=until,
    )
    return AuditEventPage(
        data=[AuditEventInfo.model_validate(event) for event in page.items],
        next=page_link(request, page.next_cursor),
        prev=page_link(request, page.prev_cursor),
    )
