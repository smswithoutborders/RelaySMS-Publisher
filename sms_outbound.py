"""
This program is free software: you can redistribute it under the terms
of the GNU General Public License, v. 3.0. If a copy of the GNU General
Public License was not distributed with this file, see <https://www.gnu.org/licenses/>.
"""

from twilio.rest import Client
from twilio.base.exceptions import TwilioRestException
from utils import get_configs
from logutils import get_logger

TWILIO_ACCOUNT_SID = get_configs("TWILIO_ACCOUNT_SID", strict=True)
TWILIO_AUTH_TOKEN = get_configs("TWILIO_AUTH_TOKEN", strict=True)
TWILIO_SERVICE_SID = get_configs("TWILIO_SERVICE_SID", strict=True)
TWILIO_PHONE_NUMBER = get_configs("TWILIO_PHONE_NUMBER", strict=True)

logger = get_logger(__name__)


def send_with_twilio(phone_number: str, message: str) -> bool:
    """
    Sends a message using Twilio to a specified phone number.

    Args:
        phone_number (str): The recipient's phone number in E.164 format (e.g., +237123456789).
        message (str): The content to be sent to the specified phone number.

    Returns:
        bool: True if the message was sent successfully, False otherwise.
    """
    client = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)

    try:
        message_response = client.messages.create(
            body=message, from_=TWILIO_PHONE_NUMBER, to=phone_number
        )
        status = message_response.status

        if status in ("accepted", "pending", "queued"):
            logger.info("Message sent successfully.")
            return True

        logger.error("Failed to send message. Twilio status: %s", status)

        return True
    except TwilioRestException as exc:
        logger.error("Error sending message with Twilio: %s", exc)
        return False
