# Reliability Testing Specification for Gateway Clients

This outlines how to perform reliability testing for gateway clients using the Test Platform. The test is designed to measure how reliable a gateway client is in receiving and routing SMS messages accurately and promptly.

---

## Purpose
To evaluate the **reliability** of gateway clients by simulating message delivery and tracking key metrics such as received time, routed time, and overall success status.

---

## Ideal Payload Format for Publishing to the Test Platform
The payload published to the gateway client should contain the following fields in this format:

```
1712544600:1:123456789
```

- `1712544600` – Unix timestamp (start time)  
- `1` – Test ID (returned when starting the test)  
- `123456789` – Gateway client number

---

## Steps to Perform a Reliability Test

### 1. Start the Test
Send a request to the gateway server using the endpoint:

**POST** `/v3/clients/<msisdn>/tests`

#### Request Body:
```json
{
  "test_start_time": "2025-04-08T01:25:00"
}
```

#### Response:
```json
{
  "message": "Test started successfully",
  "test_id": "1",
  "test_start_time": "1746799899" // test start time in unix time
}
```

The test is saved in the database with a `pending` status.

---

### 2. Publish to the Gateway Client
Send the ideal payload format to the gateway client using the regular publish flow:

```
1712544600:1:123456789
```

Where:
- `start_time` is the Unix timestamp returned from the API
- `id` is the Test ID returned from the API
- `msisdn` is the gateway client number

The ID is used to reference the test that was previously started.

---

### 3. Message is Published to the Test Platform
If the message reaches the Test Platform, it will be saved in the database.

- The server extracts metadata such as `sms_received_time` and `sms_routed_time` from the request.
- The reliability score for the gateway client is automatically calculated.

---

## Fetching Reliability Test Results
Use the endpoint to fetch reliability data:

**GET** `/v3/clients/<msisdn>/tests`

### Optional Filters:
- `start_time`
- `status`
- `msisdn`

---
