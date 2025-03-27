import datetime
import requests
from logutils import get_logger
from db_models import ReliabilityTests
from db import database

logger = get_logger(__name__)


class TestClient:
    """
    SMS Test Platform Client.
    """

    def __init__(self):

        pass

    def send_test_message(
        self,
        start_time,
        sms_sent_time,
        sms_received_time,
        sms_routed_time,
        status,
        msisdn,
    ):

        timestamp = datetime.datetime.utcnow().isoformat()

        # Save the message in the database
        try:
            with database.atomic():
                ReliabilityTests.create(
                    timestamp=timestamp,
                    start_time=start_time,
                    sms_sent_time=sms_sent_time,
                    sms_received_time=sms_received_time,
                    sms_routed_time=sms_routed_time,
                    status=status,
                    msisdn=msisdn,
                )
            logger.info("Successfully saved test message to database.")
        except Exception as e:
            logger.error("Failed to save test message: %s", str(e))
            return None, str(e)

        return None, None
