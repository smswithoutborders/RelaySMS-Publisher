# Publisher REST API Documentation

The Publisher REST API provides metadata about supported platforms and server identity keys required for gRPC v3 communication.

## Base URL

```
http://<host>:<port>/v1
```

## Endpoints

### 1. List Platforms

Retrieve a list of supported platform adapter manifests.

**URL:** `/platforms`  
**Method:** `GET`

**Response Body:** `List[PlatformManifest]`

| Field | Type | Description |
| :--- | :--- | :--- |
| name | string | Full name of the platform (e.g., "Gmail") |
| shortcode | string | Platform shortcode (e.g., "g") |
| protocol_type | string | Protocol used (e.g., "oauth2", "pnba") |
| cat_id | integer | Category identifier |
| icon_svg | string | (Optional) SVG icon data |
| icon_png | string | (Optional) PNG icon URL/data |
| support_url_scheme | boolean | (Optional) Whether it supports custom URL schemes |

---

### 2. Get Platform Manifest

Retrieve the manifest for a specific platform.

**URL:** `/platforms/{platform_name}`  
**Method:** `GET`

**Parameters:**

- `platform_name`: The name of the platform (e.g., "gmail").

**Response Body:** `PlatformManifest` (see above)

---

### 3. List Server Static Keys

Retrieve all server static public keys used for gRPC v3 encryption.

**URL:** `/server-keys`  
**Method:** `GET`

**Response Body:** `List[ServerStaticPublicKey]`

| Field | Type | Description |
| :--- | :--- | :--- |
| key_id | integer | Static key identifier (0-255) |
| public_key | string | Base64url-encoded X25519 public key |

---

### 4. Get Server Static Key

Retrieve a specific server static public key by its ID.

**URL:** `/server-keys/{key_id}`  
**Method:** `GET`

**Parameters:**

- `key_id`: The ID of the key (0-255).

**Response Body:** `ServerStaticPublicKey` (see above)

---

### 5. Get OAuth Client Metadata

Retrieve OAuth2 client metadata for platforms that require dynamic registration or specific client details (e.g., Bluesky).

**URL:** `/platforms/{platform_name}/oauth/client-metadata.json`  
**Method:** `GET`

**Parameters:**

- `platform_name`: The name of the platform.

**Response Body:** `OAuthClientMetadata`

| Field | Type | Description |
| :--- | :--- | :--- |
| client_id | string | OAuth2 Client ID |
| client_name | string | Application name |
| redirect_uris | list[string] | Allowed redirect URIs |
| scope | string | Requested scopes |
| ... | ... | Other standard OAuth2 client metadata fields |

---

### 6. Publish Content

Submit an encrypted payload for publication to a target platform.

**URL:** `/publications`
**Method:** `POST`

**Request Body:** `PublishContentRequest`

| Field | Type | Description |
| :--- | :--- | :--- |
| address | string | Sender phone number in E.164 format (e.g., `+12025550123`) |
| text | string | Base64-encoded serialized payload |

**Response Body:** `PublishContentResponse`

| Field | Type | Description |
| :--- | :--- | :--- |
| message | string | (Optional) Confirmation message on success |
| error | string | (Optional) Error description on failure |

## Error Handling

The API returns standard HTTP status codes:

- `200 OK`: Request successful.
- `400 Bad Request`: Invalid request parameters or payload.
- `404 Not Found`: Platform or Key not found.
- `422 Unprocessable Entity`: Validation error in request parameters.
- `500 Internal Server Error`: Unexpected server error.
