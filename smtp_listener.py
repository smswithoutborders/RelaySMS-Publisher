# SPDX-License-Identifier: GPL-3.0-only
"""SMTP transport: polls a relay mailbox over IMAP and hands each message
to the publication pipeline."""

import imaplib
import json
import socket
import ssl
import time
import traceback

from imap_tools import (
    AND,
    MailBox,
    MailboxDeleteError,
    MailboxFolderSelectError,
    MailboxLoginError,
    MailboxLogoutError,
    MailMessage,
)
from pydantic import ValidationError

import smtp_auth
from logutils import get_logger
from publications import (
    PayloadMalformedError,
    PayloadNotSupportedError,
    PublicationService,
)
from rest_services.v1.schemas import PublishContentRequest
from tasks.publication_task import publish_message
from utils import get_config_bool, get_config_list, get_configs

logger = get_logger("publisher.smtp.listener")

SMTP_TRANSPORT_ENABLED = get_config_bool("SMTP_TRANSPORT_ENABLED")

if SMTP_TRANSPORT_ENABLED:
    IMAP_SERVER = get_configs("SMTP_IMAP_SERVER", strict=True)
    IMAP_PORT = int(get_configs("SMTP_IMAP_PORT", default_value="993"))
    IMAP_USERNAME = get_configs("SMTP_IMAP_USERNAME", strict=True)
    IMAP_PASSWORD = get_configs("SMTP_IMAP_PASSWORD", strict=True)
    MAIL_FOLDERS = get_config_list("SMTP_IMAP_MAIL_FOLDER", default_value=["INBOX"])
    TLS_CLIENT_CERTIFICATE = get_configs("SMTP_TLS_CLIENT_CERTIFICATE")
    TLS_CLIENT_KEY = get_configs("SMTP_TLS_CLIENT_KEY")
else:
    IMAP_SERVER = IMAP_PORT = IMAP_USERNAME = IMAP_PASSWORD = MAIL_FOLDERS = None
    TLS_CLIENT_CERTIFICATE = TLS_CLIENT_KEY = None


def _mask_email(address: str) -> str:
    local, _, domain = (address or "").partition("@")
    if not domain:
        return "***"
    return f"{local[:2]}***@{domain}"


def process_incoming_email(msg: MailMessage) -> bool:
    """Validate, authenticate, and queue an incoming email for publication.

    Returns whether the email is done with (should be deleted). False means
    an unexpected error occurred and it should be left for a retry next
    cycle; every other outcome, handled or intentionally rejected, is done.
    """
    email_uid = msg.uid
    from_email = msg.from_

    try:
        if not from_email:
            logger.warning("No valid 'From' found. Discarding email %s.", email_uid)
            return True

        if not smtp_auth.is_sender_allowed(from_email):
            logger.warning(
                "Dropping email %s from unauthorized sender: %s",
                email_uid,
                _mask_email(from_email),
            )
            return True

        # as_bytes() re-serializes rather than returning the literal wire
        # bytes, but dkimpy tolerates that (see smtp_auth.verify_dkim_independently).
        auth_passed, auth_reason = smtp_auth.evaluate(
            msg.obj, msg.obj.as_bytes(), from_email
        )
        if not auth_passed:
            logger.warning(
                "Dropping email %s failing authentication (sender %s): %s",
                email_uid,
                _mask_email(from_email),
                auth_reason,
            )
            return True

        try:
            request = PublishContentRequest(**json.loads(msg.text))
        except (json.JSONDecodeError, ValidationError, TypeError) as exc:
            logger.warning("Discarding email %s with invalid body: %s", email_uid, exc)
            return True

        try:
            PublicationService.validate(request.text)
        except (PayloadMalformedError, PayloadNotSupportedError) as exc:
            logger.warning(
                "Discarding email %s with invalid payload: %s", email_uid, exc
            )
            return True

        publish_message.delay(request.text, request.address, "smtp")
        logger.info(
            "Successfully queued publication request from email %s via protocol %r.",
            email_uid,
            "smtp",
        )
        return True

    except Exception:
        logger.exception("Error processing email %s", email_uid)
        return False


def main() -> None:
    """Run the SMTP (IMAP-polling) ingestion loop."""
    if not SMTP_TRANSPORT_ENABLED:
        logger.info(
            "SMTP transport disabled (SMTP_TRANSPORT_ENABLED != true). Exiting."
        )
        return

    ssl_context = ssl.create_default_context()
    if TLS_CLIENT_CERTIFICATE and TLS_CLIENT_KEY:
        ssl_context.load_cert_chain(
            certfile=TLS_CLIENT_CERTIFICATE, keyfile=TLS_CLIENT_KEY
        )

    done = False
    while not done:
        connection_start_time = time.monotonic()
        connection_live_time = 0.0
        try:
            with MailBox(IMAP_SERVER, IMAP_PORT, ssl_context=ssl_context).login(
                IMAP_USERNAME, IMAP_PASSWORD
            ) as mailbox:
                logger.info(
                    "Connected to mailbox %s on %s", IMAP_SERVER, time.asctime()
                )
                while connection_live_time < 29 * 60:
                    try:
                        responses = mailbox.idle.wait(timeout=20)
                        if responses:
                            logger.debug("IMAP IDLE responses: %s", responses)

                        for folder in MAIL_FOLDERS:
                            try:
                                mailbox.folder.set(folder)
                            except MailboxFolderSelectError:
                                logger.error(
                                    "Folder %r does not exist, skipping", folder
                                )
                                continue
                            to_delete = [
                                msg.uid
                                for msg in mailbox.fetch(
                                    criteria=AND(seen=False),
                                    bulk=50,
                                    mark_seen=False,
                                )
                                if process_incoming_email(msg) and msg.uid
                            ]
                            if to_delete:
                                try:
                                    mailbox.delete(to_delete)
                                except MailboxDeleteError as exc:
                                    logger.error(
                                        "Failed to delete %d email(s): %s",
                                        len(to_delete),
                                        exc,
                                    )

                    except KeyboardInterrupt:
                        logger.info("Received KeyboardInterrupt, exiting...")
                        done = True
                        break
                    connection_live_time = time.monotonic() - connection_start_time
        except (
            TimeoutError,
            ConnectionError,
            imaplib.IMAP4.abort,
            MailboxLoginError,
            MailboxLogoutError,
            socket.herror,
            socket.gaierror,
            socket.timeout,
        ) as e:
            logger.error("Error occurred: %s", e)
            logger.error(traceback.format_exc())
            logger.info("Reconnecting in a minute...")
            time.sleep(60)


if __name__ == "__main__":
    main()
