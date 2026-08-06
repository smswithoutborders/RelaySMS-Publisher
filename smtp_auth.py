# SPDX-License-Identifier: GPL-3.0-only
"""Sender authentication for the SMTP transport.

Two independent checks, both required: an allowlist of who may send at all,
and trust in the receiving mail server's own Authentication-Results header
(RFC 8601) rather than re-deriving SPF/DKIM ourselves - by the time a
message reaches us over IMAP, the sender's connecting IP is long gone, but
the mailbox's own MTA already checked it in real time. That header is only
trusted when its authserv-id matches SMTP_TRUSTED_AUTHSERV_ID, since a
sender could otherwise forge their own passing header.
"""

import re
from email.message import Message
from typing import Optional

import authres
import dkim

from logutils import get_logger
from utils import get_config_bool, get_config_list, get_configs

logger = get_logger(__name__)

_FOLD_RE = re.compile(r"\r?\n[ \t]+")


def _load_allowed_senders() -> set[str]:
    return {
        entry.lower().lstrip("@") for entry in get_config_list("SMTP_ALLOWED_SENDERS")
    }


SMTP_ALLOWED_SENDERS = _load_allowed_senders()
SMTP_TRUSTED_AUTHSERV_ID = get_configs("SMTP_TRUSTED_AUTHSERV_ID")
SMTP_REQUIRE_DKIM = get_config_bool("SMTP_REQUIRE_DKIM", True)
SMTP_REQUIRE_SPF = get_config_bool("SMTP_REQUIRE_SPF", True)
SMTP_VERIFY_DKIM_INDEPENDENTLY = get_config_bool(
    "SMTP_VERIFY_DKIM_INDEPENDENTLY", False
)


def is_sender_allowed(email_address: str) -> bool:
    """Check a From address against SMTP_ALLOWED_SENDERS."""
    address = (email_address or "").strip().lower()
    if not SMTP_ALLOWED_SENDERS or "@" not in address:
        return False
    domain = address.rsplit("@", 1)[1]
    return address in SMTP_ALLOWED_SENDERS or domain in SMTP_ALLOWED_SENDERS


def _trusted_result(msg: Message) -> Optional[authres.AuthenticationResultsHeader]:
    """First Authentication-Results header matching SMTP_TRUSTED_AUTHSERV_ID, if any.

    Headers from any other (or missing) authserv-id are ignored, since a
    sender can put arbitrary text of their own in this header.
    """
    if not SMTP_TRUSTED_AUTHSERV_ID:
        return None
    for raw_value in msg.get_all("Authentication-Results") or []:
        try:
            header = authres.AuthenticationResultsHeader.parse(
                f"Authentication-Results: {_FOLD_RE.sub(' ', raw_value)}"
            )
        except Exception as exc:  # authres raises plain Exception subclasses
            logger.debug("Failed to parse Authentication-Results header: %s", exc)
            continue
        if header.authserv_id == SMTP_TRUSTED_AUTHSERV_ID:
            return header
    return None


def evaluate_authentication(msg: Message) -> tuple[bool, str]:
    """Check SPF/DKIM verdicts from a trusted Authentication-Results header."""
    if not SMTP_TRUSTED_AUTHSERV_ID:
        return True, "SMTP_TRUSTED_AUTHSERV_ID not configured; check skipped"

    header = _trusted_result(msg)
    if header is None:
        return False, (
            f"No Authentication-Results header from trusted authserv-id "
            f"{SMTP_TRUSTED_AUTHSERV_ID!r}"
        )

    results = {result.method: result.result for result in header.results}
    if SMTP_REQUIRE_DKIM and results.get("dkim") != "pass":
        return False, "DKIM verdict is not 'pass'"
    if SMTP_REQUIRE_SPF and results.get("spf") != "pass":
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
    if not signing_domain or not from_domain.endswith(signing_domain):
        return False, (
            f"DKIM signing domain {signing_domain!r} does not align with "
            f"From domain {from_domain!r}"
        )
    return True, "Independent DKIM verification passed"


def evaluate(msg: Message, raw_bytes: bytes, from_email: str) -> tuple[bool, str]:
    """Run all configured authentication checks for an incoming email."""
    passed, reason = evaluate_authentication(msg)
    if passed and SMTP_VERIFY_DKIM_INDEPENDENTLY:
        passed, reason = verify_dkim_independently(raw_bytes, from_email)
    return passed, reason
