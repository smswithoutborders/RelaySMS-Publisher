# Reliability Testing Specification for Gateway Clients

This document outlines how to perform reliability testing for gateway clients using the Test Platform. The test is designed to measure how reliable a gateway client is in receiving and routing SMS messages accurately and promptly.

---

## Purpose

The purpose of reliability testing is to evaluate the **reliability** of gateway clients by simulating message delivery and tracking key metrics such as:
- **Received Time**: When the message is received by the gateway.
- **Routed Time**: When the message is routed to the intended recipient.
- **Success Status**: Whether the message was successfully routed within the expected timeframe.

This process ensures that gateway clients meet performance standards and helps identify potential issues in message delivery.

---

## Steps to Perform a Reliability Test

### 1. Start the Test

To initiate a reliability test, send a request to the gateway server using the following endpoint:

**Endpoint**:  
`POST /v3/clients/<msisdn>/tests`

#### Request Body:
```json
{
  "test_start_time": 1746799899 // Epoch time (in seconds)
}
```

#### Example cURL Command:
```bash
curl -X POST "https://api.example.com/v3/clients/1234567890/tests" \
-H "Content-Type: application/json" \
-d '{
  "test_start_time": 1746799899
}'
```

#### Response:
```json
{
  "message": "Test started successfully",
  "test_id": 1,
  "test_start_time": 1746799899
}
```

- **`test_id`**: A unique identifier for the test. This ID will be used in subsequent steps.
- **`test_start_time`**: The time the test was initiated, in epoch format.

The test is saved in the database with a `pending` status.

---

### 2. Publish to the Gateway Client

Once the test is started, send the test payload to the gateway client using the regular publish flow.

#### Payload Format:
The payload must include the `test_id`, which is **encrypted** like all other platform payloads. Encryption ensures the security and integrity of the data during transmission.

For more details on the payload content format, refer to the [Encryption Guidelines](/docs/specification.md).

#### Example Encrypted Payload:
```json
{
  "payload": "ENCRYPTED_CONTENT"
}
```

Where:
- **`ENCRYPTED_CONTENT`**: The encrypted version of the `test_id`.

#### Example cURL Command:
```bash
curl -X POST "https://api.example.com/v3/publish" \
-H "Content-Type: application/json" \
-d '{
  "payload": "ENCRYPTED_CONTENT"
}'
```

---

### 3. Message is Published to the Test Platform

If the message reaches the Test Platform, it will be saved in the database. The platform will automatically extract and store the following metadata:
- **`sms_received_time`**: The time the message was received by the Gateway server.
- **`sms_sent_time`**: Provider says it is the time the sender sent the message.

The reliability score for the gateway client is then calculated based on the following criteria:
- **Success**: The message is routed within 3 minutes (180 seconds) of being received.
- **Failure**: The message is not routed within the expected timeframe.

---

## Fetching Reliability Test Results

To retrieve the results of a reliability test, use the following endpoint:

**Endpoint**:  
`GET /v3/clients/<msisdn>/tests`

### Optional Filters:
- **`start_time`**: Fetch tests that started after this time (epoch format).
- **`status`**: Filter by test status (`pending`, `success`, `timedout`.).
- **`msisdn`**: Fetch tests for a specific MSISDN.

#### Example cURL Command:
```bash
curl -X GET "https://api.example.com/v3/clients/1234567890/tests?status=success&start_time=1746790000" \
-H "Authorization: Bearer <your_access_token>"
```

#### Response:
```json
[
  {
    "test_id": 1,
    "msisdn": "1234567890",
    "status": "success",
    "sms_received_time": 1746799900,
    "sms_routed_time": 1746799950,
    "reliability_score": 95.0
  },
  {
    "test_id": 2,
    "msisdn": "1234567890",
    "status": "timedout",
    "sms_received_time": 1746799000,
    "sms_routed_time": null,
    "reliability_score": 0.0
  }
]
```

---

## Understanding Reliability Scores

The reliability score is calculated as the percentage of successful message routings out of the total number of tests conducted for a specific MSISDN. A successful routing is defined as:
- The message is routed within 5 minutes (300 seconds) of being received.

### Example:
- **Total Tests**: 10
- **Successful Tests**: 8
- **Reliability Score**: `(8 / 10) * 100 = 80%`

---

## Common Scenarios and Troubleshooting

### Scenario 1: Test ID Not Found
If you attempt to publish a test with an invalid or non-existent `test_id`, the server will return an error:
```json
{
  "error": "Test ID not found"
}
```
**Solution**: Ensure the `test_id` is valid and corresponds to an active test.

---

### Scenario 2: Test Timed Out
If a test exceeds the 10-minute timeout period without being completed, its status will be updated to `timedout`.

**Example Response**:
```json
{
  "test_id": 3,
  "status": "timedout",
  "message": "The test has timed out."
}
```

**Solution**: Investigate potential delays in the gateway client or network.

---

### Scenario 3: Low Reliability Score
If the reliability score is below the acceptable threshold, it indicates issues with message delivery or routing.

**Solution**:
- Check the gateway client logs for errors.
- Ensure the client is configured correctly to handle test payloads.


---

