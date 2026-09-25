# Publisher REST API Documentation

The Publisher REST API provides metadata about supported platforms, registered gateway clients, and server identity keys required for gRPC v3 communication, as well as an endpoint for publishing encrypted content and publication stats.

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
| tag | string | No | Shared secret matching `OFFLINE_PUBLISH_SHARED_SECRET`; required for offline payloads when that variable is set. See [Offline Publishing](../README.md#offline-publishing). |

**Response Body:** `PublishContentResponse`

| Field | Type | Description |
| :--- | :--- | :--- |
| message | string | (Optional) Status message (e.g., confirmation or waiting-for-segments notice) |

**Payload types handled:**

| Type | Behaviour |
| :--- | :--- |
| `WITHOUT_ATTACHMENT` | Deserialized and published immediately |
| `WITH_ATTACHMENT_HEADER` / `WITH_ATTACHMENT_NO_HEADER` | Segment stored; once all segments are assembled the full payload is published |

Payloads queued here are tagged with protocol `https`. If `OFFLINE_PUBLISH_ALLOWED_PROTOCOLS` is set without `https`, offline payloads are discarded instead of published. If `OFFLINE_PUBLISH_SHARED_SECRET` is set, offline payloads also require a matching `tag`. See [Offline Publishing](../README.md#offline-publishing).

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

**Forwarding to additional URLs:** Twilio only supports one webhook URL. Set `TWILIO_FORWARD_URLS_RAW` and/or `TWILIO_FORWARD_URLS_JSON` (comma-separated) to forward each inbound SMS.

* `TWILIO_FORWARD_URLS_RAW`: same form-encoded params Twilio sent (`From`, `Body`, `MessageSid`, ...)
* `TWILIO_FORWARD_URLS_JSON`: normalized `{"sender", "text", "received_at"}` JSON body

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

### 10. List Publication Stats

List publish attempts.

**URL:** `/stats/publications`
**Method:** `GET`
**Auth:** Optional

**Query Parameters:**

| Parameter | Type | Required | Description |
| :--- | :--- | :--- | :--- |
| status | string | No | Filter by status (e.g. `published`, `failed`) |
| platform_name | string | No | Filter by platform name |
| protocol | string | No | Filter by ingestion protocol (e.g. `https`, `smtp`, `sms`) |
| country_code | string | No | Filter by ISO country code (e.g. `CM`) |
| since | datetime | No | Rows created at or after this time (ISO-8601; UTC if no offset) |
| until | datetime | No | Rows created before this time (ISO-8601; UTC if no offset) |
| limit | integer | No | Page size, 1–200 (default `50`) |
| cursor | string | No | Set by the `next`/`prev` links. Don't build it yourself. |

Filter values accept alphanumerics, `_` and `-`.

**Response Body:**

```json
{
  "data": [
    {
      "id": 1042,
      "platform_name": "gmail",
      "protocol": "sms",
      "status": "failed",
      "country_code": "CM",
      "created_at": "2026-09-24T10:39:30Z",
      "failure_reason": "token_expired"
    }
  ],
  "next": "https://<host>/v1/stats/publications?status=failed&limit=50&cursor=eyJ0Ijoi...",
  "prev": null
}
```

`failure_reason` is admin-only. Follow `next` and `prev` as-is: they keep your filters and `limit`, and are `null` on the last and first page.

### 11. Publication Stats Summary

Count publish attempts per group over a time window.

**URL:** `/stats/publications/summary`
**Method:** `GET`
**Auth:** Optional (required to group by `failure_reason`)

**Query Parameters:**

| Parameter | Type | Required | Description |
| :--- | :--- | :--- | :--- |
| group_by | string | No | `status` (default), `platform_name`, `protocol`, `country_code` or `failure_reason` (admin only). Repeatable. |
| since | datetime | No | Window start (default: 30 days before `until`) |
| until | datetime | No | Window end (default: now) |
| interval | string | No | `day`, `week`, `month` or `year`. Adds a `period` field: the period start in UTC. Weeks start Monday. |
| status, platform_name, protocol, country_code | string | No | Same filters as [List Publication Stats](#10-list-publication-stats) |

Public requests can't span more than 366 days. Groups are sorted by `period`, then `count` descending.

**Response Body** for `?interval=month&group_by=status`:

```json
{
  "since": "2026-07-01T00:00:00Z",
  "until": "2026-09-01T00:00:00Z",
  "interval": "month",
  "total": 95,
  "groups": [
    { "count": 40, "period": "2026-07-01T00:00:00Z", "status": "published" },
    { "count": 5, "period": "2026-07-01T00:00:00Z", "status": "failed" },
    { "count": 48, "period": "2026-08-01T00:00:00Z", "status": "published" },
    { "count": 2, "period": "2026-08-01T00:00:00Z", "status": "failed" }
  ]
}
```

If `interval` isn't set, it's `null` in the response and groups have no `period`. Periods with no rows are omitted; treat them as `0` when charting.

### 12. Admin Login

Start a web session. Sets an `HttpOnly` session cookie and returns a CSRF token.

**URL:** `/auth/login`
**Method:** `POST`

**Request Body:**

```json
{ "email": "admin@example.org", "password": "<password>" }
```

**Response Body:** `AdminMe`

```json
{
  "email": "admin@example.org",
  "auth_method": "session",
  "csrf_token": "<token>",
  "expires_at": "2026-09-24T22:00:00Z"
}
```

Bad credentials and disabled accounts return the same `401`. An `Origin` other than this API or `ADMIN_WEB_ORIGINS` returns `403`.

### 13. Admin Logout

End the current session and clear the cookie.

**URL:** `/auth/logout`
**Method:** `POST`
**Auth:** Session cookie + `X-CSRF-Token` header

**Response:** `204 No Content`

### 14. Current Admin

Return the authenticated admin. Call it on page load to check the session and get the CSRF token.

**URL:** `/auth/me`
**Method:** `GET`
**Auth:** Session cookie or Basic

**Response Body:** `AdminMe`. `csrf_token` and `expires_at` are `null` for Basic auth.

## Admin Authentication

Admins are managed with [`./admin-users.sh`](../README.md#admin-users).

* **Web session:** `POST /v1/auth/login`, then send the cookie with every request (`credentials: "include"` in `fetch`) and the `csrf_token` as `X-CSRF-Token` on `POST`s. Sessions end after 30 minutes idle or 12 hours.
* **HTTP Basic:** email and password on every request, e.g. `curl -u admin@example.org:<password> .../v1/stats/publications`. HTTPS only.

### Web clients on another origin

Add each web client's origin to `ADMIN_WEB_ORIGINS` (exact origins, no wildcards) to allow credentialed CORS.

> [!WARNING]
> On an unrelated domain the cookie is third-party, and Safari, Firefox and Brave block or restrict it. Use a subdomain of the API's domain, or proxy `/v1` through the web client's domain.

## Error Handling

The API uses standard HTTP status codes. Error bodies are `{"error": "<message>"}`:

| Status | Meaning |
| :--- | :--- |
| `200 OK` | Request successful |
| `400 Bad Request` | Invalid request parameters or payload, invalid cursor, or invalid time window |
| `401 Unauthorized` | Missing or invalid admin credentials |
| `403 Forbidden` | Origin not allowed, missing/invalid CSRF token, or admin-only option |
| `404 Not Found` | Platform or key not found |
| `422 Unprocessable Entity` | Unsupported payload type or validation error |
| `429 Too Many Requests` | Rate limited (login and Basic-auth requests) |
| `500 Internal Server Error` | Unexpected server-side error |
