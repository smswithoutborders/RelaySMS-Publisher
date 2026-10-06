# SPDX-License-Identifier: GPL-3.0-only

import logging

from fastapi import APIRouter, HTTPException, Request, Response
from twilio.request_validator import RequestValidator
from twilio.twiml.messaging_response import MessagingResponse

from publisher import publications
from publisher.api.rest.v1.schemas import (
    PublishContentResponse,
    PublishRestContentRequest,
)
from publisher.config import TwilioConfig
from publisher.publications import PayloadMalformedError
from publisher.tasks.forward_task import forward_twilio_webhook
from publisher.tasks.publication_task import publish_message

logger = logging.getLogger(__name__)

twilio_config = TwilioConfig.get()

router = APIRouter(tags=["Publishing"])


@router.post("/publications", response_model=PublishContentResponse, summary="Publish")
def create_publications(body: PublishRestContentRequest) -> PublishContentResponse:
    """Queues an SMS payload for publishing.

    Multi-part payloads are kept until every segment arrives, then published. Payloads
    are tagged with protocol `https`; see Offline Publishing in the README for
    `OFFLINE_PUBLISH_ALLOWED_PROTOCOLS` and `tag`. Decryption and adapter errors
    happen later in the queue, so they're logged, not returned.
    """
    try:
        publications.validate(body.text)
    except PayloadMalformedError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    publish_message.delay(body.text, body.address, "https", body.tag)
    logger.info("Successfully queued publication request via protocol %r.", "https")
    return PublishContentResponse(message="Publication request queued successfully.")


@router.post("/twilio-sms", summary="Twilio SMS webhook")
async def twilio_incoming_sms(request: Request) -> Response:
    """Checks the Twilio signature, then queues the SMS for publishing.

    Takes Twilio's form-encoded webhook (`From`, `Body`) and answers with empty TwiML.
    Returns 404 unless `TWILIO_SMS_TRANSPORT_ENABLED=true`, and 403 without a valid
    `X-Twilio-Signature`. Payloads are tagged with protocol `sms`. Each SMS is also
    forwarded to `TWILIO_FORWARD_URLS_RAW` as Twilio's form and to
    `TWILIO_FORWARD_URLS_JSON` as `{"sender", "text", "received_at"}`.
    """
    if not twilio_config.sms_transport_enabled:
        raise HTTPException(status_code=404, detail="Not Found")

    form = await request.form()
    params = dict(form)
    signature = request.headers.get("X-Twilio-Signature", "")

    validator = RequestValidator(twilio_config.auth_token)
    if not validator.validate(str(request.url), params, signature):
        logger.warning("Rejected Twilio webhook with invalid signature.")
        raise HTTPException(status_code=403, detail="Invalid Twilio signature.")

    sender_address = params.get("From")
    text_payload = params.get("Body")

    if not isinstance(sender_address, str) or not isinstance(text_payload, str):
        raise HTTPException(
            status_code=400, detail="Missing required field 'From' or 'Body'."
        )

    try:
        publications.validate(text_payload)
    except PayloadMalformedError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    publish_message.delay(text_payload, sender_address, "sms")
    logger.info("Successfully queued publication request via protocol %r.", "sms")

    forward_twilio_webhook.delay(params, sender_address, text_payload)

    return Response(content=str(MessagingResponse()), media_type="text/xml")
