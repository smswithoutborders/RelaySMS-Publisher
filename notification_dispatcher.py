"""
This program is free software: you can redistribute it under the terms
of the GNU General Public License, v. 3.0. If a copy of the GNU General
Public License was not distributed with this file, see <https://www.gnu.org/licenses/>.
"""

import concurrent.futures
import threading
import sentry_sdk
from logutils import get_logger
from sms_outbound import (
    send_with_twilio,
    send_with_queuedroid,
    get_phonenumber_region_code,
    QUEUEDROID_SUPPORTED_REGION_CODES,
)
from publications import create_publication_entry

logger = get_logger(__name__)


def send_sms_notification(phone_number: str, message: str):
    """Send an SMS notification.

    Args:
        phone_number (str): Recipient's phone number.
        message (str): Message content.

    Returns:
        bool: True if sent successfully, False otherwise.
    """
    region_code = get_phonenumber_region_code(phone_number)
    if region_code not in QUEUEDROID_SUPPORTED_REGION_CODES:
        return send_with_twilio(phone_number, message)

    return send_with_queuedroid(phone_number, message)


def send_event(
    event_type: str,
    details: dict = None,
    message: str = None,
    exception: Exception = None,
) -> None:
    """Store an event in the database.

    Args:
        event_type (str): The type of event (e.g., "publication")
        details (dict, optional): Additional parameters.
        message (str, optional): The message content.
        exception (Exception, optional): The exception object.
    """
    match event_type:
        case "publication":
            create_publication_entry(**details)
        case "sentry":
            level = details.get("level")
            capture_type = details.get("capture_type")

            sentry = getattr(sentry_sdk, f"capture_{capture_type}")
            data = message if capture_type == "message" else exception
            logger.debug("Notification event: %s", data)
            sentry(data, level=level)
        case _:
            logger.error("Invalid event type: %s", event_type)


def dispatch_notifications(notifications: list):
    """Dispatch multiple notifications concurrently using ThreadPoolExecutor.

    Args:
        notifications (list): A list of notification dictionaries, each containing:
            - notification_type (str): Type of notification ("sms", "event").
            - target (str): The recipient (phone number for SMS, or event type for event storage).
            - message (str, optional): The message content.
            - exception (Exception, optional): The exception object.
            - details (dict, optional): Additional parameters.
    """

    def _dispatch(notification):
        notification_type = notification.get("notification_type")
        target = notification.get("target")
        message = notification.get("message")
        details = notification.get("details")
        exception = notification.get("exception")

        match notification_type:
            case "sms":
                send_sms_notification(phone_number=target, message=message)
            case "event":
                send_event(
                    event_type=target,
                    details=details,
                    message=message,
                    exception=exception,
                )
            case _:
                logger.error("Invalid notification type: %s", notification_type)

    def _run_in_background():
        with concurrent.futures.ThreadPoolExecutor() as executor:
            for notification in notifications:
                executor.submit(_dispatch, notification)

    thread = threading.Thread(target=_run_in_background, daemon=True)
    thread.start()
