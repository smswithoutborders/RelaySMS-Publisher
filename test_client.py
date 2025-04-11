"""
This program is free software: you can redistribute it under the terms
of the GNU General Public License, v. 3.0. If a copy of the GNU General
Public License was not distributed with this file, see https://www.gnu.org/licenses/.
"""

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

    def update_reliability_test(
        self, test_id, sms_sent_time, sms_received_time, sms_routed_time
    ):
        try:
            
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

    def calculate_reliability_score_for_client(msisdn: str) -> float:
        """
        Calculate the reliability score for a gateway client based on successful SMS routing.

        Args:
            msisdn (str): The MSISDN of the client.

        Returns:
            float: Reliability percentage rounded to two decimal places.

        Notes:
            This function calculates the reliability score for a given client based on the
            percentage of successful SMS routings within a 3-minute window. Reliability is
            defined as the ratio of successful SMS routings to the total number of tests
            conducted for the client.

            A successful SMS routing is defined as a routing with a 'success' status, where
            the SMS is routed within 180 seconds (3 minutes) of being received by the system.
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
                    <= 300
                ),
            )
            .count()
        )

        reliability = (successful_tests / total_tests) * 100

        return round(reliability, 2)