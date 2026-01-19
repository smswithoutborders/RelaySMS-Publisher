# Publisher gRPC Documentation

## Table of Contents

- [Download Protocol Buffer Files](#download-protocol-buffer-files)
- [Prerequisites](#prerequisites)
- [Version 2 API](#version-2-api)
  - [v2: Get OAuth2 Authorization URL](#v2-get-oauth2-authorization-url)
  - [v2: Exchange OAuth2 Code and Store Token](#v2-exchange-oauth2-code-and-store-token)
  - [v2: Revoke and Delete OAuth2 Token](#v2-revoke-and-delete-oauth2-token)
  - [v2: Get PNBA Code](#v2-get-pnba-code)
  - [v2: Exchange PNBA Code and Store Token](#v2-exchange-pnba-code-and-store-token)
  - [v2: Revoke and Delete PNBA Token](#v2-revoke-and-delete-pnba-token)
- [Version 1 API](#version-1-api)
  - [v1: Get OAuth2 Authorization URL](#v1-get-oauth2-authorization-url)
  - [v1: Exchange OAuth2 Code and Store Token](#v1-exchange-oauth2-code-and-store-token)
  - [v1: Revoke and Delete OAuth2 Token](#v1-revoke-and-delete-oauth2-token)
  - [v1: Get PNBA Code](#v1-get-pnba-code)
  - [v1: Exchange PNBA Code and Store Token](#v1-exchange-pnba-code-and-store-token)
  - [v1: Revoke and Delete PNBA Token](#v1-revoke-and-delete-pnba-token)
  - [v1: Publish Content](#v1-publish-content)

## Download Protocol Buffer Files

### Version 2

```bash
curl -O -L https://raw.githubusercontent.com/smswithoutborders/RelaySMS-Publisher/staging/protos/v2/publisher.proto
```

**Package:** `publisher.v2`  
**Service:** `Publisher`

### Version 1

```bash
curl -O -L https://raw.githubusercontent.com/smswithoutborders/RelaySMS-Publisher/staging/protos/v1/publisher.proto
```

**Package:** `publisher.v1`  
**Service:** `Publisher`

## Prerequisites

### Install Dependencies

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

For other languages, see [Supported languages](https://grpc.io/docs/languages/).

### Compile gRPC

**For Version 2:**

```bash
python -m grpc_tools.protoc -I protos/v2 --python_out=. --grpc_python_out=. protos/v2/publisher.proto
```

**For Version 1:**

```bash
python -m grpc_tools.protoc -I protos/v1 --python_out=. --grpc_python_out=. protos/v1/publisher.proto
```

### Starting the Server

```bash
GRPC_PORT=<your_port> \
GRPC_HOST=<your_host> \
python3 grpc_server.py
```

---

## Version 2 API

**Package:** `publisher.v2`  
**Service:** `Publisher`

---

### v2: Get OAuth2 Authorization URL

Generates an OAuth2 authorization URL for initiating the OAuth2 flow.

> [!NOTE]
>
> #### Supported Platforms
>
> | Platform Name | Shortcode | Service Type | Protocol | PKCE     |
> | ------------- | --------- | ------------ | -------- | -------- |
> | Gmail         | g         | Email        | OAuth2   | Optional |
> | Twitter       | t         | Text         | OAuth2   | Required |
> | Telegram      | T         | Message      | PNBA     | N/A      |
> | Reliability   | r         | Test         | event    | N/A      |
> | Bluesky       | b         | Text         | OAuth2   | Required |

**Request:** `GetOAuth2AuthorizationUrlRequest`

| Field                      | Type   | Required | Description                                                   |
| -------------------------- | ------ | -------- | ------------------------------------------------------------- |
| platform                   | string | Yes      | Platform identifier (e.g., "gmail")                           |
| state                      | string | Optional | State parameter to prevent CSRF attacks                       |
| code_verifier              | string | Optional | Cryptographic random string for PKCE                          |
| autogenerate_code_verifier | bool   | Optional | Auto-generate code verifier if not provided                   |
| redirect_url               | string | Optional | Redirect URL for OAuth2 application                           |
| request_identifier         | string | Optional | Request identifier for tracking                               |

**Response:** `GetOAuth2AuthorizationUrlResponse`

| Field             | Type   | Description                               |
| ----------------- | ------ | ----------------------------------------- |
| authorization_url | string | Generated authorization URL               |
| state             | string | State parameter from request              |
| code_verifier     | string | Code verifier used in PKCE flow           |
| message           | string | Response message                          |
| scope             | string | Authorization request scope               |
| client_id         | string | OAuth2 application client ID              |
| redirect_url      | string | OAuth2 application redirect URL           |

**Example:**

```bash
grpcurl -plaintext -d @ -proto protos/v2/publisher.proto \
<your_host>:<your_port> publisher.v2.Publisher/GetOAuth2AuthorizationUrl <<EOF
{
  "platform": "gmail",
  "state": "",
  "code_verifier": "",
  "autogenerate_code_verifier": true,
  "request_identifier": ""
}
EOF
```

---

### v2: Exchange OAuth2 Code and Store Token

Exchanges an OAuth2 authorization code for access and refresh tokens, and stores them in the vault.

> [!WARNING]
>
> - This action requires authentication headers.

**Request:** `ExchangeOAuth2CodeAndStoreRequest`

| Field              | Type   | Required | Description                             |
| ------------------ | ------ | -------- | --------------------------------------- |
| platform           | string | Yes      | Platform identifier                     |
| authorization_code | string | Yes      | OAuth2 authorization code               |
| code_verifier      | string | Optional | Code verifier for PKCE                  |
| redirect_url       | string | Optional | Redirect URL for OAuth2 application     |
| store_on_device    | bool   | Optional | Store token on device instead of cloud  |
| request_identifier | string | Optional | Request identifier for tracking         |

**Headers:**

| Header        | Type   | Required | Description                                                  |
| ------------- | ------ | -------- | ------------------------------------------------------------ |
| authorization | string | Yes      | Bearer token (format: `Bearer <long_lived_token>`)           |
| x-sig         | string | Yes      | Request signature (base64 url-safe encoded)                  |
| x-nonce       | string | Yes      | Nonce for request (must be unique, base64 url-safe encoded)  |
| x-timestamp   | string | Yes      | Request timestamp                                            |

**Response:** `ExchangeOAuth2CodeAndStoreResponse`

| Field   | Type                | Description                         |
| ------- | ------------------- | ----------------------------------- |
| success | bool                | Operation success                   |
| message | string              | Response message                    |
| tokens  | map<string, string> | Access, refresh, and ID tokens      |

**Example:**

```bash
grpcurl -plaintext \
-H 'authorization: Bearer your_long_lived_token' \
-H 'x-sig: your_signature_base64_urlsafe' \
-H 'x-nonce: unique_nonce_base64_urlsafe' \
-H 'x-timestamp: timestamp' \
-d @ -proto protos/v2/publisher.proto \
<your_host>:<your_port> publisher.v2.Publisher/ExchangeOAuth2CodeAndStore <<EOF
{
  "platform": "gmail",
  "authorization_code": "auth_code",
  "code_verifier": "abcdef",
  "store_on_device": false,
  "request_identifier": ""
}
EOF
```

---

### v2: Revoke and Delete OAuth2 Token

Revokes and deletes an OAuth2 token from the vault.

> [!WARNING]
>
> - This action requires authentication headers.

**Request:** `RevokeAndDeleteOAuth2TokenRequest`

| Field              | Type   | Required | Description        |
| ------------------ | ------ | -------- | ------------------ |
| platform           | string | Yes      | Platform name      |
| account_identifier | string | Yes      | Account identifier |

**Headers:**

| Header        | Type   | Required | Description                                                  |
| ------------- | ------ | -------- | ------------------------------------------------------------ |
| authorization | string | Yes      | Bearer token (format: `Bearer <long_lived_token>`)           |
| x-sig         | string | Yes      | Request signature (base64 url-safe encoded)                  |
| x-nonce       | string | Yes      | Nonce for request (must be unique, base64 url-safe encoded)  |
| x-timestamp   | string | Yes      | Request timestamp                                            |

**Response:** `RevokeAndDeleteOAuth2TokenResponse`

| Field   | Type   | Description       |
| ------- | ------ | ----------------- |
| message | string | Response message  |
| success | bool   | Operation success |

**Example:**

```bash
grpcurl -plaintext \
-H 'authorization: Bearer your_long_lived_token' \
-H 'x-sig: your_signature_base64_urlsafe' \
-H 'x-nonce: unique_nonce_base64_urlsafe' \
-H 'x-timestamp: timestamp' \
-d @ -proto protos/v2/publisher.proto \
<your_host>:<your_port> publisher.v2.Publisher/RevokeAndDeleteOAuth2Token <<EOF
{
  "platform": "gmail",
  "account_identifier": "sample@mail.com"
}
EOF
```

---

### v2: Get PNBA Code

Sends a one-time passcode (OTP) to the user's phone number for Phone Number-Based Authentication.

**Request:** `GetPNBACodeRequest`

| Field              | Type   | Required | Description                         |
| ------------------ | ------ | -------- | ----------------------------------- |
| platform           | string | Yes      | Platform identifier (e.g., "telegram") |
| phone_number       | string | Yes      | Phone number to receive OTP         |
| request_identifier | string | Optional | Request identifier for tracking     |

**Response:** `GetPNBACodeResponse`

| Field   | Type   | Description       |
| ------- | ------ | ----------------- |
| success | bool   | Operation success |
| message | string | Response message  |

**Example:**

```bash
grpcurl -plaintext -d @ -proto protos/v2/publisher.proto \
<your_host>:<your_port> publisher.v2.Publisher/GetPNBACode <<EOF
{
  "phone_number": "1234567890",
  "platform": "telegram",
  "request_identifier": ""
}
EOF
```

---

### v2: Exchange PNBA Code and Store Token

Exchanges a one-time passcode (OTP) for an access token and stores it in the vault.

> [!WARNING]
>
> - This action requires authentication headers.

**Request:** `ExchangePNBACodeAndStoreRequest`

| Field              | Type   | Required | Description                             |
| ------------------ | ------ | -------- | --------------------------------------- |
| platform           | string | Yes      | Platform identifier                     |
| phone_number       | string | Yes      | Phone number that received OTP          |
| authorization_code | string | Yes      | PNBA authorization code                 |
| password           | string | Optional | Password for two-step verification      |
| request_identifier | string | Optional | Request identifier for tracking         |

**Headers:**

| Header        | Type   | Required | Description                                                  |
| ------------- | ------ | -------- | ------------------------------------------------------------ |
| authorization | string | Yes      | Bearer token (format: `Bearer <long_lived_token>`)           |
| x-sig         | string | Yes      | Request signature (base64 url-safe encoded)                  |
| x-nonce       | string | Yes      | Nonce for request (must be unique, base64 url-safe encoded)  |
| x-timestamp   | string | Yes      | Request timestamp                                            |

**Response:** `ExchangePNBACodeAndStoreResponse`

| Field                         | Type   | Description                         |
| ----------------------------- | ------ | ----------------------------------- |
| success                       | bool   | Operation success                   |
| message                       | string | Response message                    |
| two_step_verification_enabled | bool   | Two-step verification status        |

**Example:**

```bash
grpcurl -plaintext \
-H 'authorization: Bearer your_long_lived_token' \
-H 'x-sig: your_signature_base64_urlsafe' \
-H 'x-nonce: unique_nonce_base64_urlsafe' \
-H 'x-timestamp: timestamp' \
-d @ -proto protos/v2/publisher.proto \
<your_host>:<your_port> publisher.v2.Publisher/ExchangePNBACodeAndStore <<EOF
{
  "authorization_code": "auth_code",
  "password": "",
  "phone_number": "+1234567890",
  "platform": "telegram",
  "request_identifier": ""
}
EOF
```

---

### v2: Revoke and Delete PNBA Token

Revokes and deletes a PNBA token from the vault.

> [!WARNING]
>
> - This action requires authentication headers.

**Request:** `RevokeAndDeletePNBATokenRequest`

| Field              | Type   | Required | Description        |
| ------------------ | ------ | -------- | ------------------ |
| platform           | string | Yes      | Platform name      |
| account_identifier | string | Yes      | Account identifier |

**Headers:**

| Header        | Type   | Required | Description                                                  |
| ------------- | ------ | -------- | ------------------------------------------------------------ |
| authorization | string | Yes      | Bearer token (format: `Bearer <long_lived_token>`)           |
| x-sig         | string | Yes      | Request signature (base64 url-safe encoded)                  |
| x-nonce       | string | Yes      | Nonce for request (must be unique, base64 url-safe encoded)  |
| x-timestamp   | string | Yes      | Request timestamp                                            |

**Response:** `RevokeAndDeletePNBATokenResponse`

| Field   | Type   | Description       |
| ------- | ------ | ----------------- |
| message | string | Response message  |
| success | bool   | Operation success |

**Example:**

```bash
grpcurl -plaintext \
-H 'authorization: Bearer your_long_lived_token' \
-H 'x-sig: your_signature_base64_urlsafe' \
-H 'x-nonce: unique_nonce_base64_urlsafe' \
-H 'x-timestamp: timestamp' \
-d @ -proto protos/v2/publisher.proto \
<your_host>:<your_port> publisher.v2.Publisher/RevokeAndDeletePNBAToken <<EOF
{
  "platform": "telegram",
  "account_identifier": "1234567890"
}
EOF
```

---

## Version 1 API

**Package:** `publisher.v1`  
**Service:** `Publisher`

---

### v1: Get OAuth2 Authorization URL

Generates an OAuth2 authorization URL for initiating the OAuth2 flow.

> [!NOTE]
>
> #### Supported Platforms
>
> | Platform Name | Shortcode | Service Type | Protocol | PKCE     |
> | ------------- | --------- | ------------ | -------- | -------- |
> | Gmail         | g         | Email        | OAuth2   | Optional |
> | Twitter       | t         | Text         | OAuth2   | Required |
> | Telegram      | T         | Message      | PNBA     | N/A      |
> | Reliability   | r         | Test         | event    | N/A      |
> | Bluesky       | b         | Text         | OAuth2   | Required |

**Request:** `GetOAuth2AuthorizationUrlRequest`

| Field                      | Type   | Required | Description                                                   |
| -------------------------- | ------ | -------- | ------------------------------------------------------------- |
| platform                   | string | Yes      | Platform identifier (e.g., "gmail")                           |
| state                      | string | Optional | State parameter to prevent CSRF attacks                       |
| code_verifier              | string | Optional | Cryptographic random string for PKCE                          |
| autogenerate_code_verifier | bool   | Optional | Auto-generate code verifier if not provided                   |
| redirect_url               | string | Optional | Redirect URL for OAuth2 application                           |
| request_identifier         | string | Optional | Request identifier for tracking                               |

**Response:** `GetOAuth2AuthorizationUrlResponse`

| Field             | Type   | Description                               |
| ----------------- | ------ | ----------------------------------------- |
| authorization_url | string | Generated authorization URL               |
| state             | string | State parameter from request              |
| code_verifier     | string | Code verifier used in PKCE flow           |
| message           | string | Response message                          |
| scope             | string | Authorization request scope               |
| client_id         | string | OAuth2 application client ID              |
| redirect_url      | string | OAuth2 application redirect URL           |

**Example:**

```bash
grpcurl -plaintext -d @ -proto protos/v1/publisher.proto \
<your_host>:<your_port> publisher.v1.Publisher/GetOAuth2AuthorizationUrl <<EOF
{
  "platform": "gmail",
  "state": "",
  "code_verifier": "",
  "autogenerate_code_verifier": true,
  "request_identifier": ""
}
EOF
```

---

### v1: Exchange OAuth2 Code and Store Token

Exchanges an OAuth2 authorization code for access and refresh tokens, and stores them in the vault.

> [!NOTE]
>
> Ensure you have generated your authorization URL before using this function.
> Use the following recommended parameters:
>
> ##### Gmail
>
> - **scope:**
>   - `openid`
>   - `https://www.googleapis.com/auth/gmail.send`
>   - `https://www.googleapis.com/auth/userinfo.profile`
>   - `https://www.googleapis.com/auth/userinfo.email`
> - **access_type:** `offline`
> - **prompt:** `consent`
>
> A well-generated Gmail authorization URL will look something like this:
>
> ```bash
> https://accounts.google.com/o/oauth2/auth?response_type=code&client_id=your_application_client_id&redirect_uri=your_application_redirect_uri&scope=openid+https%3A%2F%2Fwww.googleapis.com%2Fauth%2Fgmail.send+https%3A%2F%2Fwww.googleapis.com%2Fauth%2Fuserinfo.email+https%3A%2F%2Fwww.googleapis.com%2Fauth%2Fuserinfo.profile&state=random_state_string&prompt=consent&access_type=offline
> ```
>
> ##### Twitter
>
> - **scope:**
>   - `tweet.write`
>   - `users.read`
>   - `tweet.read`
>   - `offline.access`
> - **code_challenge:** `generated code challenge`
> - **code_challenge_method:** `S256`
>
> A well-generated Twitter authorization URL will look something like this:
>
> ```bash
> https://twitter.com/i/oauth2/authorize?response_type=code&client_id=your_application_client_id&redirect_uri=your_application_redirect_uri&scope=tweet.write+users.read+tweet.read+offline.access&state=kr5sa8LtHL1mkjq7oOtWlH06Rb0dQM&code_challenge=code_challenge&code_challenge_method=S256
> ```

**Request:** `ExchangeOAuth2CodeAndStoreRequest`

| Field              | Type   | Required | Description                             |
| ------------------ | ------ | -------- | --------------------------------------- |
| long_lived_token   | string | Yes      | Long-lived token for authentication     |
| platform           | string | Yes      | Platform identifier                     |
| authorization_code | string | Yes      | OAuth2 authorization code               |
| code_verifier      | string | Optional | Code verifier for PKCE                  |
| redirect_url       | string | Optional | Redirect URL for OAuth2 application     |
| store_on_device    | bool   | Optional | Store token on device instead of cloud  |
| request_identifier | string | Optional | Request identifier for tracking         |

**Response:** `ExchangeOAuth2CodeAndStoreResponse`

| Field   | Type                | Description                         |
| ------- | ------------------- | ----------------------------------- |
| success | bool                | Operation success                   |
| message | string              | Response message                    |
| tokens  | map<string, string> | Access, refresh, and ID tokens      |

**Example:**

```bash
grpcurl -plaintext -d @ -proto protos/v1/publisher.proto \
<your_host>:<your_port> publisher.v1.Publisher/ExchangeOAuth2CodeAndStore <<EOF
{
  "long_lived_token": "long_lived_token",
  "platform": "gmail",
  "authorization_code": "auth_code",
  "code_verifier": "abcdef",
  "store_on_device": false,
  "request_identifier": ""
}
EOF
```

---

### v1: Revoke and Delete OAuth2 Token

Revokes and deletes an OAuth2 token from the vault.

**Request:** `RevokeAndDeleteOAuth2TokenRequest`

| Field              | Type   | Required | Description                      |
| ------------------ | ------ | -------- | -------------------------------- |
| long_lived_token   | string | Yes      | Long-lived token for authentication |
| platform           | string | Yes      | Platform name                    |
| account_identifier | string | Yes      | Account identifier               |

**Response:** `RevokeAndDeleteOAuth2TokenResponse`

| Field   | Type   | Description       |
| ------- | ------ | ----------------- |
| message | string | Response message  |
| success | bool   | Operation success |

**Example:**

```bash
grpcurl -plaintext -d @ -proto protos/v1/publisher.proto \
<your_host>:<your_port> publisher.v1.Publisher/RevokeAndDeleteOAuth2Token <<EOF
{
  "long_lived_token": "long_lived_token",
  "platform": "gmail",
  "account_identifier": "sample@mail.com"
}
EOF
```

---

### v1: Get PNBA Code

Sends a one-time passcode (OTP) to the user's phone number for Phone Number-Based Authentication.

**Request:** `GetPNBACodeRequest`

| Field              | Type   | Required | Description                         |
| ------------------ | ------ | -------- | ----------------------------------- |
| platform           | string | Yes      | Platform identifier (e.g., "telegram") |
| phone_number       | string | Yes      | Phone number to receive OTP         |
| request_identifier | string | Optional | Request identifier for tracking     |

**Response:** `GetPNBACodeResponse`

| Field   | Type   | Description       |
| ------- | ------ | ----------------- |
| success | bool   | Operation success |
| message | string | Response message  |

**Example:**

```bash
grpcurl -plaintext -d @ -proto protos/v1/publisher.proto \
<your_host>:<your_port> publisher.v1.Publisher/GetPNBACode <<EOF
{
  "phone_number": "+1234567890",
  "platform": "telegram",
  "request_identifier": ""
}
EOF
```

---

### v1: Exchange PNBA Code and Store Token

Exchanges a one-time passcode (OTP) for an access token and stores it in the vault.

**Request:** `ExchangePNBACodeAndStoreRequest`

| Field              | Type   | Required | Description                             |
| ------------------ | ------ | -------- | --------------------------------------- |
| long_lived_token   | string | Yes      | Long-lived token for authentication     |
| platform           | string | Yes      | Platform identifier                     |
| phone_number       | string | Yes      | Phone number that received OTP          |
| authorization_code | string | Yes      | PNBA authorization code                 |
| password           | string | Optional | Password for two-step verification      |
| request_identifier | string | Optional | Request identifier for tracking         |

**Response:** `ExchangePNBACodeAndStoreResponse`

| Field                         | Type   | Description                         |
| ----------------------------- | ------ | ----------------------------------- |
| success                       | bool   | Operation success                   |
| message                       | string | Response message                    |
| two_step_verification_enabled | bool   | Two-step verification status        |

**Example:**

```bash
grpcurl -plaintext -d @ -proto protos/v1/publisher.proto \
<your_host>:<your_port> publisher.v1.Publisher/ExchangePNBACodeAndStore <<EOF
{
  "authorization_code": "auth_code",
  "long_lived_token": "long_lived_token",
  "password": "",
  "phone_number": "+1234567890",
  "platform": "telegram",
  "request_identifier": ""
}
EOF
```

---

### v1: Revoke and Delete PNBA Token

Revokes and deletes a PNBA token from the vault.

**Request:** `RevokeAndDeletePNBATokenRequest`

| Field              | Type   | Required | Description                      |
| ------------------ | ------ | -------- | -------------------------------- |
| long_lived_token   | string | Yes      | Long-lived token for authentication |
| platform           | string | Yes      | Platform name                    |
| account_identifier | string | Yes      | Account identifier               |

**Response:** `RevokeAndDeletePNBATokenResponse`

| Field   | Type   | Description       |
| ------- | ------ | ----------------- |
| message | string | Response message  |
| success | bool   | Operation success |

**Example:**

```bash
grpcurl -plaintext -d @ -proto protos/v1/publisher.proto \
<your_host>:<your_port> publisher.v1.Publisher/RevokeAndDeletePNBAToken <<EOF
{
  "long_lived_token": "long_lived_token",
  "platform": "telegram",
  "account_identifier": "+1234567890"
}
EOF
```

---

### v1: Publish Content

Publishes a RelaySMS payload.

**Request:** `PublishContentRequest`

| Field    | Type                | Required | Description              |
| -------- | ------------------- | -------- | ------------------------ |
| content  | string              | Yes      | Content payload          |
| metadata | map<string, string> | Yes      | Metadata about content   |

**Response:** `PublishContentResponse`

| Field              | Type   | Description                     |
| ------------------ | ------ | ------------------------------- |
| success            | bool   | Operation success               |
| message            | string | Response message                |
| publisher_response | string | Encrypted response from publisher |

**Example:**

```bash
grpcurl -plaintext -d @ -proto protos/v1/publisher.proto \
<your_host>:<your_port> publisher.v1.Publisher/PublishContent <<EOF
{
  "content": "encoded_relay_sms_payload",
  "metadata": {
    "From": "+1234567890"
  }
}
EOF
```

---

> [!NOTE]
>
>All gRPC responses return standard status codes. `0 OK` indicates success. See [gRPC Status Codes](https://grpc.github.io/grpc/core/md_doc_statuscodes.html) for error codes.
