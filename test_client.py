import datetime
import requests
from logutils import get_logger
from db_models import ReliabilityTests
from db import connect

logger = get_logger(__name__)
database = connect()

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

    def update_test_message(self, test_id, sms_sent_time):
        """
        Updates an existing test message in the database.

        Args:
            test_id (int): The ID of the test to update.
            sms_sent_time (datetime): The time the SMS was sent.

        Returns:
            tuple: (None, error) if an error occurs, otherwise (None, None).
        """
        try:
            logger.debug(f"Updating test message with ID: {test_id}, SMS sent time: {sms_sent_time}")
            logger.debug(f"test_id type: {type(test_id)}, sms_sent_time type: {type(sms_sent_time)}")

            # Ensure test_id is an integer
            if not isinstance(test_id, int):
                raise TypeError(f"test_id must be an integer, got {type(test_id)}")

            # Ensure sms_sent_time is a datetime object
            if not isinstance(sms_sent_time, datetime.datetime):
                raise TypeError(f"sms_sent_time must be a datetime object, got {type(sms_sent_time)}")

            with database.atomic():
                # Query the database for the test record using test_id
                test_record = ReliabilityTests.get(ReliabilityTests.id == test_id)

                # Update the test record with the new information
                test_record.sms_sent_time = sms_sent_time
                test_record.status = "done"  # Update the status to 'done'
                test_record.save()

            logger.info("Successfully updated test message in database.")
            return None, None
        except ReliabilityTests.DoesNotExist:
            error_message = f"Test ID {test_id} not found in the database."
            logger.error(error_message)
            return None, error_message
        except Exception as e:
            logger.error("Failed to update test message: %s", str(e))
            return None, str(e)
