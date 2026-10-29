# SPDX-License-Identifier: GPL-3.0-only

from fastapi import APIRouter, HTTPException

from publisher import publications
from publisher.api.rest.v1.errors import error_responses
from publisher.api.rest.v1.schemas import (
    PublishContentResponse,
    PublishRestContentRequest,
)
from publisher.publications import PayloadMalformedError
from publisher.tasks.publication_task import queue_publication

router = APIRouter(tags=["Publishing"])


@router.post(
    "/publications",
    response_model=PublishContentResponse,
    summary="Publish",
    responses=error_responses(
        {400: "The payload isn't base64, or isn't a RelaySMS payload."}
    ),
)
def create_publications(body: PublishRestContentRequest) -> PublishContentResponse:
    """Queues an SMS payload for publishing.

    Multi-part payloads are kept until every segment arrives, then published. Payloads
    are tagged with protocol `https`. See Offline publishing in the manual for
    `OFFLINE_PUBLISH_ALLOWED_PROTOCOLS` and `tag`. Decryption and adapter errors are
    logged, not returned.
    """
    try:
        publications.validate(body.text)
    except PayloadMalformedError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    queue_publication(
        body.text, body.address, "https", tag=body.tag, dialing_code=body.dialing_code
    )
    return PublishContentResponse(message="Publication request queued successfully.")
