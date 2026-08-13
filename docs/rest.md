# Publisher REST API Documentation

The Publisher REST API provides metadata about supported platforms, registered gateway clients, and server identity keys required for gRPC v3 communication, as well as an endpoint for publishing encrypted content.

## Base URL

```
http://<host>:<port>/v1
```

## Endpoints

### 1. List Platforms

Retrieve a list of supported platform adapter manifests. Supports optional query filters.

**URL:** `/platforms`
**Method:** `GET`

**Query Parameters:**

| Parameter | Type | Required | Description |
| :--- | :--- | :--- | :--- |
| name | string | No | Filter by platform name (alphanumeric, `_`, `-`; max 50 chars) |
| proto_id | integer | No | Filter by protocol ID (e.g., `0` = oauth2, `1` = pnba) |
| cat_id | integer | No | Filter by category ID |

**Response Body:** `List[PlatformManifest]`

| Field | Type | Description |
| :--- | :--- | :--- |
| name | string | Full name of the platform (e.g., `"gmail"`) |
| shortcode | string | Platform shortcode (e.g., `"g"`) |
| proto_id | integer | Protocol identifier (`0` = oauth2, `1` = pnba) |
| cat_id | integer | Category identifier |
| icon_svg | string | (Optional) Inline SVG icon data |
| icon_png | string | (Optional) PNG icon URL or data |
| supports_offline_first | boolean | (Optional) Whether the platform adapter supports offline-first payloads |

### 2. List Gateway Clients

Retrieve a list of registered gateway clients. Supports optional query filters.

**URL:** `/gateway-clients`
**Method:** `GET`

**Query Parameters:**

| Parameter | Type | Required | Description |
| :--- | :--- | :--- | :--- |
| msisdn | string | No | Filter by MSISDN |
| country | string | No | Filter by country |
| operator | string | No | Filter by operator |

**Response Body:** `List[GatewayClientManifest]`

| Field | Type | Description |
| :--- | :--- | :--- |
| msisdn | string | Gateway client's phone number in E.164 format |
| country | string | Country the MSISDN belongs to |
| operator | string | Mobile network operator |
| operator_code | string | PLMN (MCC+MNC) code |
| protocols | list[string] | Protocol(s) the client uses to reach this server |

### 3. List Server Static Keys

Retrieve all server static public keys used for gRPC v3 encryption.

**URL:** `/server-keys`
**Method:** `GET`

**Response Body:** `List[ServerStaticPublicKey]`

| Field | Type | Description |
| :--- | :--- | :--- |
| key_id | integer | Static key identifier (0–255) |
| public_key | string | Base64url-encoded X25519 public key |

### 4. Get Server Static Key

Retrieve a specific server static public key by its ID.

**URL:** `/server-keys/{key_id}`
**Method:** `GET`

**Path Parameters:**

| Parameter | Type | Required | Description |
| :--- | :--- | :--- | :--- |
| key_id | integer | Yes | Key identifier, must be in range 0–255 |

**Response Body:** `ServerStaticPublicKey` (see above)

**Error Responses:**

| Status | Condition |
| :--- | :--- |
| `404 Not Found` | No key exists for the given `key_id` |

### 5. Get OAuth Client Metadata

Retrieve OAuth2 client metadata for platforms that support dynamic registration (e.g., Bluesky). Only available for a fixed allow-list of platforms.

**URL:** `/platforms/{platform_name}/oauth/client-metadata.json`
**Method:** `GET`

**Path Parameters:**

| Parameter | Type | Required | Description |
| :--- | :--- | :--- | :--- |
| platform_name | string | Yes | Platform name (alphanumeric, `_`, `-`) |

**Response Body:** `OAuthClientMetadata`

| Field | Type | Description |
| :--- | :--- | :--- |
| client_id | string | OAuth2 Client ID |
| client_name | string | Application name |
| client_uri | string | Application URI |
| application_type | string | Application type (e.g., `"web"`) |
| redirect_uris | list[string] | Allowed redirect URIs |
| grant_types | list[string] | Supported grant types |
| response_types | list[string] | Supported response types |
| scope | string | Requested scopes |
| token_endpoint_auth_method | string | Authentication method for the token endpoint |
| dpop_bound_access_tokens | boolean | Whether DPoP-bound access tokens are required |

**Error Responses:**

| Status | Condition |
| :--- | :--- |
| `404 Not Found` | Platform not found, not in the allow-list, or `credentials.json` is missing |

### 6. OAuth Callback

Displays the OAuth2 callback parameters returned by a platform. Intended as a redirect target during the OAuth2 authorization flow.

**URL:** `/platforms/{platform_name}/oauth/callback`
**Method:** `GET`

**Path Parameters:**

| Parameter | Type | Required | Description |
| :--- | :--- | :--- | :--- |
| platform_name | string | Yes | Platform name (alphanumeric, `_`, `-`) |

**Query Parameters:** All query parameters forwarded by the OAuth provider (e.g., `code`, `state`) are captured and displayed in an HTML table.

**Response:** `200 OK`, HTML page listing all callback parameters.

**Error Responses:**

| Status | Condition |
| :--- | :--- |
| `404 Not Found` | Platform not found or not in the allow-list |

### 7. Publish Content

Submit an encrypted SMS payload for decryption and publication to its target platform. Handles both single-part payloads and multi-part segmented payloads (assembled before publishing).

**URL:** `/publications`
**Method:** `POST`

**Request Body:** `PublishContentRequest`

| Field | Type | Required | Description |
| :--- | :--- | :--- | :--- |
| address | string | Yes | Sender phone number in E.164 format (e.g., `+12025550123`) |
| text | string | Yes | Base64-encoded serialized payload |

**Response Body:** `PublishContentResponse`

| Field | Type | Description |
| :--- | :--- | :--- |
| message | string | (Optional) Status message (e.g., confirmation or waiting-for-segments notice) |

**Payload types handled:**

| Type | Behaviour |
| :--- | :--- |
| `WITHOUT_ATTACHMENT` | Deserialized and published immediately |
| `WITH_ATTACHMENT_HEADER` / `WITH_ATTACHMENT_NO_HEADER` | Segment stored; once all segments are assembled the full payload is published |

Payloads queued here are tagged with protocol `https`. If `OFFLINE_PUBLISH_ALLOWED_PROTOCOLS` is set without `https`, offline payloads are discarded instead of published. See [Offline Publishing](../README.md#offline-publishing).

**Error Responses:**

| Status | Condition |
| :--- | :--- |
| `400 Bad Request` | Invalid base64 text or invalid payload structure |

Decryption, unsupported payload type, unsupported protocol, and adapter errors are all detected later, inside the async publish pipeline, so they never surface as an HTTP error here. They're logged server-side only.

### 8. Twilio Incoming SMS

Ingests an inbound SMS relayed by Twilio's messaging webhook and queues it for publication. Disabled unless `TWILIO_SMS_TRANSPORT_ENABLED=true`.

**URL:** `/twilio-sms`
**Method:** `POST`
**Content-Type:** `application/x-www-form-urlencoded` (Twilio's webhook format)

**Request Parameters** (subset of Twilio's webhook payload that's used):

| Field | Type | Required | Description |
| :--- | :--- | :--- | :--- |
| From | string | Yes | Sender phone number in E.164 format |
| Body | string | Yes | Base64-encoded serialized payload |

**Authentication:** requires a valid `X-Twilio-Signature` header, verified against `TWILIO_AUTH_TOKEN`. Requests failing this check are rejected before the payload is touched.

**Response:** empty TwiML (`<Response/>`), `Content-Type: text/xml`.

Payloads queued here are tagged with protocol `sms`. If `OFFLINE_PUBLISH_ALLOWED_PROTOCOLS` is set without `sms`, offline payloads are discarded instead of published. See [Offline Publishing](../README.md#offline-publishing).

**Error Responses:**

| Status | Condition |
| :--- | :--- |
| `400 Bad Request` | Missing `From`/`Body`, invalid base64 text, or invalid payload structure |
| `403 Forbidden` | Missing or invalid `X-Twilio-Signature` |
| `404 Not Found` | `TWILIO_SMS_TRANSPORT_ENABLED` is not `true` |

Decryption, unsupported payload type, unsupported protocol, and adapter errors are all detected later, inside the async publish pipeline, so they never surface as an HTTP error here. They're logged server-side only.

### 9. Health Check

Liveness/readiness check for uptime monitoring. Verifies a database session can be opened.

**URL:** `/health` (not under `/v1`)
**Method:** `GET`

**Response Body:**

```json
{ "status": "ok" }
```

## Error Handling

The API uses standard HTTP status codes:

| Status | Meaning |
| :--- | :--- |
| `200 OK` | Request successful |
| `400 Bad Request` | Invalid request parameters or payload |
| `404 Not Found` | Platform or key not found |
| `422 Unprocessable Entity` | Unsupported payload type or validation error |
| `500 Internal Server Error` | Unexpected server-side error |
