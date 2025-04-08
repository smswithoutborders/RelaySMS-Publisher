import datetime
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

    def update_test_message(
        self, test_id, sms_sent_time, sms_received_time, sms_routed_time
    ):
        try:
            if not isinstance(test_id, int):
                raise TypeError(f"test_id must be an integer, got {type(test_id)}")

            if not isinstance(sms_sent_time, datetime.datetime):
                raise TypeError(
                    f"sms_sent_time must be a datetime object, got {type(sms_sent_time)}"
                )

            with database.atomic():
                test_record = ReliabilityTests.get(ReliabilityTests.id == test_id)

                test_record.sms_sent_time = sms_sent_time
                test_record.sms_received_time = sms_received_time
                test_record.sms_routed_time = sms_routed_time
                test_record.status = "success"
                test_record.save()

                reliability_score = self.calculate_reliability_score_for_client(
                    test_record.msisdn
                )

                rows_updated = (
                    ReliabilityTests.update(reliability_score=reliability_score)
                    .where(ReliabilityTests.id == test_record.id)
                    .execute()
                )

            return None, None
        except ReliabilityTests.DoesNotExist:
            error_message = f"Test ID {test_id} not found in the database."
            logger.error(error_message)
            return None, error_message
        except Exception as e:
            logger.error("Failed to update test message: %s", str(e))
            return None, str(e)

    def calculate_reliability_score_for_client(self, msisdn: str) -> float:
        """
        Calculate the reliability score for a gateway client based on successful SMS routing.

        Args:
            msisdn (str): The MSISDN of the client.

        Returns:
            float: Reliability percentage rounded to two decimal places.
        """
        total_tests = (
            ReliabilityTests.select().where(ReliabilityTests.msisdn == msisdn).count()
        )

        if total_tests == 0:
            return round(0.0, 2)

        successful_tests = (
            ReliabilityTests.select()
            .where(
                ReliabilityTests.msisdn == msisdn,
                ReliabilityTests.status == "success",
                (~ReliabilityTests.sms_routed_time.is_null()),
                (
                    (
                        ReliabilityTests.sms_routed_time.to_timestamp()
                        - ReliabilityTests.sms_received_time.to_timestamp()
                    )
                    <= 300  # 5 minutes
                ),
            )
            .count()
        )

        reliability = (successful_tests / total_tests) * 100

        return round(reliability, 2)
