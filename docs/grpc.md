# Publisher gRPC Documentation

## Table of Contents

- [Download Protocol Buffer File](#download-protocol-buffer-file)
  - [Version 1](#version-1)
- [Prerequisites](#prerequisites)
- [Usage](#usage)
  - [OAuth2](#oauth2)
    - [Get Authorization URL](#get-authorization-url)
    - [Exchange OAuth2 Code and Store Token](#exchange-oauth2-code-and-store-token-in-vault)
    - [Revoke And Delete OAuth2 Token](#revoke-and-delete-oauth2-token)
  - [Phone Number-Based Authentication (PNBA)](#phone-number-based-authentication-pnba)
    - [Request PNBA Code](#request-pnba-code)
    - [Exchange PNBA Code and Store Token](#exchange-pnba-code-and-store-token)
    - [Revoke And Delete PNBA Token](#revoke-and-delete-pnba-token)
  - [Publish Content](#publish-content)

## Download Protocol Buffer File

To use the gRPC functions, download the protocol buffer file from the
[proto](/protos/) directory corresponding to the desired version.

### Version 1

```bash
curl -O -L https://raw.githubusercontent.com/smswithoutborders/SMSWithoutBorders-Publisher/feature/grpc-api/protos/v1/publisher.proto
```

## Prerequisites

### Install Dependencies

If you're using Python, install the necessary dependencies from
`requirements.txt`. For other languages, see
[Supported languages](https://grpc.io/docs/languages/).

> [!TIP]
>
> It's recommended to set up a virtual environment to isolate your project's
> dependencies.

```bash
python3 -m venv venv
source venv/bin/activate
```

```bash
pip install -r requirements.txt
```

### Compile gRPC for Python

If you're using Python, compile the gRPC files with `protoc` to generate the
necessary Python files. For other languages, see
[Supported languages](https://grpc.io/docs/languages/).

```bash
python -m grpc_tools.protoc -I protos/v1 --python_out=. --grpc_python_out=. protos/v1/publisher.proto
```

### Starting the Server

**Quick Start (for Development Only):**

```bash
GRPC_PORT=6000 \
GRPC_HOST=127.0.0.1 \
python3 grpc_server.py
```

## Usage

### OAuth2

#### Get Authorization URL

This method generates an OAuth2 authorization URL that the client can use to
start the OAuth2 flow.

> [!NOTE]
>
> #### Supported Platforms
>
> | Platform Name | Shortcode | Service Type | Protocol | PKCE     |
> | ------------- | --------- | ------------ | -------- | -------- |
> | Gmail         | g         | Email        | OAuth2   | Optional |
> | Twitter       | t         | Text         | OAuth2   | Required |
> | Reliability   | r         | Test         | event    | N/A      |

---

##### Request

> `request` **GetOAuth2AuthorizationUrlRequest**

> [!IMPORTANT]
>
> The table lists only the required fields for this step. Other fields will be
> ignored.

| Field    | Type   | Description                                                                            |
| -------- | ------ | -------------------------------------------------------------------------------------- |
| platform | string | The platform identifier for which the authorization URL is generated. (e.g., "gmail"). |

Optional fields:

| Field                      | Type   | Description                                                                  |
| -------------------------- | ------ | ---------------------------------------------------------------------------- |
| state                      | string | An opaque value used to maintain state between the request and the callback. |
| code_verifier              | string | A cryptographic random string used in the PKCE flow.                         |
| autogenerate_code_verifier | bool   | If true, a code verifier will be auto-generated if not provided.             |

Optional fields:

| Field        | Type   | Description                                  |
| ------------ | ------ | -------------------------------------------- |
| redirect_url | string | The redirect URL for the OAuth2 application. |

---

##### Response

> `response` **GetOAuth2AuthorizationUrlResponse**

> [!IMPORTANT]
>
> The table lists only the fields that are populated for this step. Other fields
> may be empty, omitted, or false.

| Field             | Type   | Description                                                          |
| ----------------- | ------ | -------------------------------------------------------------------- |
| authorization_url | string | The generated authorization URL.                                     |
| state             | string | The state parameter sent in the request, if provided.                |
| code_verifier     | string | The code verifier used in the PKCE flow, if provided/generated.      |
| message           | string | A response message from the server.                                  |
| scope             | string | The scope of the authorization request, as a comma-separated string. |
| client_id         | string | The client ID for the OAuth2 application.                            |
| redirect_url      | string | The redirect URL for the OAuth2 application.                         |

---

##### Method

> `method` **GetOAuth2AuthorizationUrl**

> [!TIP]
>
> The examples below use
> [grpcurl](https://github.com/fullstorydev/grpcurl#grpcurl).

**Sample request**

```bash
grpcurl -plaintext \
    -d @ \
    -proto protos/v1/publisher.proto \
localhost:6000 publisher.v1.Publisher/GetOAuth2AuthorizationUrl <payload.json
```

---

**Sample payload.json**

```json
{
  "platform": "gmail",
  "state": "",
  "code_verifier": "",
  "autogenerate_code_verifier": true
}
```

---

**Sample response**

```json
{
  "authorization_url": "https://accounts.google.com/o/oauth2/auth?response_type=code&client_id=your_client_id&redirect_uri=https://example.com/callback&scope=openid%20profile&state=xyz&code_challenge=abcdef&code_challenge_method=S256",
  "state": "xyz",
  "code_verifier": "abcdef",
  "client_id": "your_client_id",
  "scope": "openid,https://www.googleapis.com/auth/gmail.send",
  "redirect_url": "https://example.com/callback",
  "message": "Successfully generated authorization url"
}
```

#### Exchange OAuth2 Code and Store Token in Vault

This method exchanges an OAuth2 authorization code for access and refresh
tokens, and fetches the user's profile information, and securely stores the
tokens in the vault.

---

> [!NOTE]
>
> Ensure you have generated your authorization URL before using this function.
> Use the following recommended parameters:
>
> ##### Gmail:
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
> Ensure to replace `your_application_client_id` and
> `your_application_redirect_uri` with your actual client ID and redirect URI.
>
> ##### Twitter:
>
> - **scope:**
>   - `tweet.write`
>   - `users.read`
>   - `tweet.read`
>   - `offline.access`
> - **code_challenge:** `generated code challenge`
> - **code_challenge_method:** `S256`
>
> A well-generated Gmail authorization URL will look something like this:
>
> ```bash
> https://twitter.com/i/oauth2/authorize?response_type=code&client_id=your_application_client_id&redirect_uri=your_application_redirect_uri&scope=tweet.write+users.read+tweet.read+offline.access&state=kr5sa8LtHL1mkjq7oOtWlH06Rb0dQM&code_challenge=code_challenge&code_challenge_method=S256
> ```
>
> Ensure to replace `your_application_client_id` and
> `your_application_redirect_uri` with your actual client ID and redirect URI.
> Replace `code_challenge` with the generated code challenge, or utilize the
> `autogenerate_code_verifier` field in the publisher's
> [Get Authorization URL](#get-authorization-url) function to assist in
> generating it.

> [!TIP]
>
> - You can use the publisher's [Get Authorization URL](#get-authorization-url)
>   function to help generate the URL for you, or utilize other tools that can
>   construct the URL.
> - The URL parameters should be Base64URL encoded. You can easily encode your
>   parameters using [Base64URL Encoder](https://www.base64url.com/).

---

##### Request

> `request` **ExchangeOAuth2CodeAndStoreRequest**

> [!IMPORTANT]
>
> The table lists only the required fields for this step. Other fields will be
> ignored.

| Field              | Type   | Description                                           |
| ------------------ | ------ | ----------------------------------------------------- |
| long_lived_token   | string | Long-lived token for authentication.                  |
| platform           | string | Platform identifier for which the code is exchanged.  |
| authorization_code | string | OAuth2 authorization code received from the provider. |

Optional fields:

| Field           | Type   | Description                                                                 |
| --------------- | ------ | --------------------------------------------------------------------------- |
| code_verifier   | string | A cryptographic random string used in the PKCE flow.                        |
| redirect_url    | string | The redirect URL for the OAuth2 application.                                |
| store_on_device | bool   | Indicates if the token should be stored on the device instead of the cloud. |

---

##### Response

> `response` **ExchangeOAuth2CodeAndStoreResponse**

> [!IMPORTANT]
>
> The table lists only the fields that are populated for this step. Other fields
> may be empty, omitted, or false.

| Field   | Type                | Description                                                                                             |
| ------- | ------------------- | ------------------------------------------------------------------------------------------------------- |
| success | bool                | Indicates if the operation was successful.                                                              |
| message | string              | A response message from the server.                                                                     |
| tokens  | map<string, string> | Contains the access, refresh, and ID tokens with keys: `access_token`, `refresh_token`, and `id_token`. |

---

##### Method

> `method` **ExchangeOAuth2CodeAndStore**

> [!TIP]
>
> The examples below use
> [grpcurl](https://github.com/fullstorydev/grpcurl#grpcurl).

**Sample request**

```bash
grpcurl -plaintext \
    -d @ \
    -proto protos/v1/publisher.proto \
localhost:6000 publisher.v1.Publisher/ExchangeOAuth2CodeAndStore <payload.json
```

---

**Sample payload.json**

```json
{
  "long_lived_token": "long_lived_token",
  "platform": "gmail",
  "authorization_code": "auth_code",
  "code_verifier": "abcdef",
  "store_on_device": false
}
```

---

**Sample response**

```json
{
  "message": "Successfully fetched and stored tokens.",
  "tokens": {},
  "success": true
}
```

---

#### Revoke And Delete OAuth2 Token

This method handles revoking and deleting an OAuth2 token from the vault.

---

##### Request

> `request` **RevokeAndDeleteOAuth2TokenRequest**

> [!IMPORTANT]
>
> The table lists only the required fields for this step. Other fields will be
> ignored.

| Field              | Type   | Description                                                |
| ------------------ | ------ | ---------------------------------------------------------- |
| long_lived_token   | string | Long-lived token for authentication.                       |
| platform           | string | Platform identifier for which the token should be revoked. |
| account_identifier | string | The identifier of the account associated with the token.   |

---

##### Response

> `response` **RevokeAndDeleteOAuth2TokenResponse**

> [!IMPORTANT]
>
> The table lists only the fields that are populated for this step. Other fields
> may be empty, omitted, or false.

| Field   | Type   | Description                                |
| ------- | ------ | ------------------------------------------ |
| message | string | A response message from the server.        |
| success | bool   | Indicates if the operation was successful. |

---

##### Method

> `method` **RevokeAndDeleteOAuth2Token**

> [!TIP]
>
> The examples below use
> [grpcurl](https://github.com/fullstorydev/grpcurl#grpcurl).

**Sample request**

```bash
grpcurl -plaintext \
    -d @ \
    -proto protos/v1/publisher.proto \
localhost:6000 publisher.v1.Publisher/RevokeAndDeleteOAuth2Token <payload.json
```

---

**Sample payload.json**

```json
{
  "long_lived_token": "long_lived_token",
  "platform": "gmail",
  "account_identifier": "sample@mail.com"
}
```

---

**Sample response**

```json
{
  "message": "Successfully deleted token",
  "success": true
}
```

### Phone Number-Based Authentication (PNBA)

#### Get PNBA Code

This method sends a one-time passcode (OTP) to the user's phone number for authentication.

---

##### Request

> `request` **GetPNBACodeRequest**

> [!IMPORTANT]
>
> The table lists only the required fields for this step. Other fields will be ignored.

| Field        | Type   | Description                                                                                |
| ------------ | ------ | ------------------------------------------------------------------------------------------ |
| phone_number | string | The phone number to which the OTP is sent.                                                 |
| platform     | string | The platform identifier for which the authorization code is generated. (e.g., "telegram"). |

---

##### Response

> `response` **GetPNBACodeResponse**

> [!IMPORTANT]
>
> The table lists only the fields that are populated for this step. Other fields may be empty, omitted, or false.

| Field   | Type   | Description                                |
| ------- | ------ | ------------------------------------------ |
| message | string | A response message from the server.        |
| success | bool   | Indicates if the operation was successful. |

---

##### Method

> `method` **GetPNBACode**

> [!TIP]
>
> The examples below use [grpcurl](https://github.com/fullstorydev/grpcurl#grpcurl).

**Sample request**

```bash
grpcurl -plaintext \
    -d @ \
    -proto protos/v1/publisher.proto \
localhost:6000 publisher.v1.Publisher/GetPNBACode <payload.json
```

---

**Sample payload.json**

```json
{
  "phone_number": "+1234567890",
  "platform": "telegram"
}
```

---

**Sample response**

```json
{
  "message": "Successfully sent authorization to your telegram app.",
  "success": true
}
```

#### Exchange PNBA Code and Store Token

This method exchanges the one-time passcode (OTP) for an access token and stores it securely in the vault.

---

##### Request

> `request` **ExchangePNBACodeAndStoreRequest**

> [!IMPORTANT]
>
> The table lists only the required fields for this step. Other fields will be ignored.

| Field              | Type   | Description                                         |
| ------------------ | ------ | --------------------------------------------------- |
| long_lived_token   | string | Long-lived token for authentication.                |
| platform           | string | Platform identifier for which the OTP is exchanged. |
| phone_number       | string | The phone number to which the OTP was sent.         |
| authorization_code | string | PNBA authorization code received from the provider. |

Optional fields:

| Field    | Type   | Description                             |
| -------- | ------ | --------------------------------------- |
| password | string | The password for two-step verification. |

---

##### Response

> `response` **ExchangePNBACodeAndStoreResponse**

> [!IMPORTANT]
>
> The table lists only the fields that are populated for this step. Other fields may be empty, omitted, or false.

| Field                         | Type   | Description                                    |
| ----------------------------- | ------ | ---------------------------------------------- |
| message                       | string | A response message from the server.            |
| two_step_verification_enabled | bool   | Indicates if two step verification is enabled. |
| success                       | bool   | Indicates if the operation was successful.     |

---

##### Method

> `method` **ExchangePNBACodeAndStore**

> [!TIP]
>
> The examples below use [grpcurl](https://github.com/fullstorydev/grpcurl#grpcurl).

**Sample request**

```bash
grpcurl -plaintext \
    -d @ \
    -proto protos/v1/publisher.proto \
localhost:6000 publisher.v1.Publisher/ExchangePNBACodeAndStore <payload.json
```

---

**Sample payload.json**

```json
{
  "authorization_code": "auth_code",
  "long_lived_token": "long_lived_token",
  "password": "",
  "phone_number": "+1234567890",
  "platform": "telegram"
}
```

---

**Sample response**

```json
{
  "success": true,
  "two_step_verification_enabled": false,
  "message": "Successfully fetched and stored token"
}
```

---

#### Revoke And Delete PNBA Token

This method handles revoking and deleting an PNBA token from the vault.

---

##### Request

> `request` **RevokeAndDeletePNBATokenRequest**

> [!IMPORTANT]
>
> The table lists only the required fields for this step. Other fields will be
> ignored.

| Field              | Type   | Description                                                |
| ------------------ | ------ | ---------------------------------------------------------- |
| long_lived_token   | string | Long-lived token for authentication.                       |
| platform           | string | Platform identifier for which the token should be revoked. |
| account_identifier | string | The identifier of the account associated with the token.   |

---

##### Response

> `response` **RevokeAndDeletePNBATokenResponse**

> [!IMPORTANT]
>
> The table lists only the fields that are populated for this step. Other fields
> may be empty, omitted, or false.

| Field   | Type   | Description                                |
| ------- | ------ | ------------------------------------------ |
| message | string | A response message from the server.        |
| success | bool   | Indicates if the operation was successful. |

---

##### Method

> `method` **RevokeAndDeletePNBAToken**

> [!TIP]
>
> The examples below use
> [grpcurl](https://github.com/fullstorydev/grpcurl#grpcurl).

**Sample request**

```bash
grpcurl -plaintext \
    -d @ \
    -proto protos/v1/publisher.proto \
localhost:6000 publisher.v1.Publisher/RevokeAndDeletePNBAToken <payload.json
```

---

**Sample payload.json**

```json
{
  "long_lived_token": "long_lived_token",
  "platform": "telegram",
  "account_identifier": "+1234567890"
}
```

---

**Sample response**

```json
{
  "message": "Successfully deleted token",
  "success": true
}
```

### Publish Content

This method handles publishing a relaysms payload.

---

##### Request

> `request` **PublishContentRequest**

> [!IMPORTANT]
>
> The table lists only the required fields for this step. Other fields will be
> ignored.

| Field    | Type                | Description                          |
| -------- | ------------------- | ------------------------------------ |
| content  | string              | The content payload to be published. |
| metadata | map<string, string> | Metadata about the content.          |

---

##### Response

> `response` **PublishContentResponse**

> [!IMPORTANT]
>
> The table lists only the fields that are populated for this step. Other fields
> may be empty, omitted, or false.

| Field              | Type   | Description                                        |
| ------------------ | ------ | -------------------------------------------------- |
| message            | string | A response message from the server.                |
| publisher_response | string | The encrypted response from the publisher, if any. |
| success            | bool   | Indicates if the operation was successful.         |

---

##### Method

> `method` **PublishContent**

> [!TIP]
>
> The examples below use
> [grpcurl](https://github.com/fullstorydev/grpcurl#grpcurl).

**Sample request**

```bash
grpcurl -plaintext \
    -d @ \
    -proto protos/v1/publisher.proto \
localhost:6000 publisher.v1.Publisher/PublishContent <payload.json
```

---

**Sample payload.json**

```json
{
  "content": "encoded_relay_sms_payload",
  "metadata": {
    "From": "+1234567890"
  }
}
```

---

**Sample response**

```json
{
  "message": "Successfully published Gmail message",
  "publisher_response": "encrypted_response_payload",
  "success": true
}
```
