# SPDX-License-Identifier: GPL-3.0-only
"""Sender authentication for the SMTP transport."""

import re
from email.message import Message
from typing import Optional

import authres
import dkim

from config import SmtpConfig
from logutils import get_logger

logger = get_logger(__name__)

smtp_config = SmtpConfig.get()

_FOLD_RE = re.compile(r"\r?\n[ \t]+")


def is_sender_allowed(email_address: str) -> bool:
    """Check a From address against SMTP_ALLOWED_SENDERS."""
    allowed = smtp_config.allowed_senders
    address = (email_address or "").strip().lower()
    if not allowed or "@" not in address:
        return False
    domain = address.rsplit("@", 1)[1]
    return address in allowed or domain in allowed


def _trusted_result(msg: Message) -> Optional[authres.AuthenticationResultsHeader]:
    """First Authentication-Results header matching SMTP_TRUSTED_AUTHSERV_ID, if any.

    Headers from any other (or missing) authserv-id are ignored, since a
    sender can put arbitrary text of their own in this header.
    """
    trusted_id = smtp_config.trusted_authserv_id
    if not trusted_id:
        return None
    for raw_value in msg.get_all("Authentication-Results") or []:
        try:
            header = authres.AuthenticationResultsHeader.parse(
                f"Authentication-Results: {_FOLD_RE.sub(' ', raw_value)}"
            )
        except Exception as exc:  # authres raises plain Exception subclasses
            logger.debug("Failed to parse Authentication-Results header: %s", exc)
            continue
        if header.authserv_id == trusted_id:
            return header
    return None


def evaluate_authentication(msg: Message) -> tuple[bool, str]:
    """Check SPF/DKIM verdicts from a trusted Authentication-Results header."""
    if not smtp_config.trusted_authserv_id:
        return False, "SMTP_TRUSTED_AUTHSERV_ID not configured; rejecting all mail"

    header = _trusted_result(msg)
    if header is None:
        return False, (
            f"No Authentication-Results header from trusted authserv-id "
            f"{smtp_config.trusted_authserv_id!r}"
        )

    results = {result.method: result.result for result in header.results}
    if smtp_config.require_dkim and results.get("dkim") != "pass":
        return False, "DKIM verdict is not 'pass'"
    if smtp_config.require_spf and results.get("spf") != "pass":
        return False, "SPF verdict is not 'pass'"
    return True, "Authentication-Results verdicts satisfied"


def verify_dkim_independently(raw_bytes: bytes, from_email: str) -> tuple[bool, str]:
    """Re-verify the DKIM signature against DNS, independent of the mailbox's own verdict."""
    try:
        d = dkim.DKIM(raw_bytes)
        verified = d.verify()
    except Exception as exc:
        logger.warning("Independent DKIM verification error: %s", exc)
        return False, f"DKIM verification error: {exc}"

    if not verified:
        return False, "Independent DKIM verification failed"

    signing_domain = (d.domain or b"").decode(errors="ignore").lower()
    from_domain = from_email.rsplit("@", 1)[-1].lower() if "@" in from_email else ""
    aligned = from_domain == signing_domain or from_domain.endswith(
        "." + signing_domain
    )
    if not signing_domain or not aligned:
        return False, (
            f"DKIM signing domain {signing_domain!r} does not align with "
            f"From domain {from_domain!r}"
        )
    return True, "Independent DKIM verification passed"


def evaluate(msg: Message, raw_bytes: bytes, from_email: str) -> tuple[bool, str]:
    """Run all configured authentication checks for an incoming email."""
    passed, reason = evaluate_authentication(msg)
    if passed and smtp_config.verify_dkim_independently:
        passed, reason = verify_dkim_independently(raw_bytes, from_email)
    return passed, reason
