# Publisher REST API Documentation

The Publisher REST API provides metadata about supported platforms and server identity keys required for gRPC v3 communication, as well as an endpoint for publishing encrypted content.

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

---

### 2. List Server Static Keys

Retrieve all server static public keys used for gRPC v3 encryption.

**URL:** `/server-keys`
**Method:** `GET`

**Response Body:** `List[ServerStaticPublicKey]`

| Field | Type | Description |
| :--- | :--- | :--- |
| key_id | integer | Static key identifier (0–255) |
| public_key | string | Base64url-encoded X25519 public key |

---

### 3. Get Server Static Key

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

---

### 4. Get OAuth Client Metadata

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

---

### 5. OAuth Callback

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

---

### 6. Publish Content

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

**Error Responses:**

| Status | Condition |
| :--- | :--- |
| `400 Bad Request` | Invalid base64 text or payload deserialization failure |
| `422 Unprocessable Entity` | Unsupported payload type |
| `500 Internal Server Error` | Decryption failure, unsupported platform/protocol, or adapter error |

---

## Error Handling

The API uses standard HTTP status codes:

| Status | Meaning |
| :--- | :--- |
| `200 OK` | Request successful |
| `400 Bad Request` | Invalid request parameters or payload |
| `404 Not Found` | Platform or key not found |
| `422 Unprocessable Entity` | Unsupported payload type or validation error |
| `500 Internal Server Error` | Unexpected server-side error |
