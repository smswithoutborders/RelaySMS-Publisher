# gRPC Flow Test CLI Client

This directory contains a CLI test tool `tests/client.py` designed to test the gRPC flows of the publisher service.

## Installation

Ensure you have all the necessary dependencies installed by running:

```sh
pip install -r requirements.txt
```

## Running the CLI Client

To run the CLI tool, use python with the module syntax:

```sh
python -m tests.client [COMMAND] [ARGS]
```

### Shared Options

The following arguments can be passed to configure the connection:

* `--host`: gRPC server host (default: `127.0.0.1`)
* `--port`: gRPC server port (default: `6000`)
* `--tls`: Use TLS for the connection
* `--rest-api`: REST API base URL (default: `http://localhost:16000`)
* `--platform`, `-p`: Platform name (e.g. `gmail`, `telegram`)
* `--phone-number`: Phone number for PNBA
* `--request-identifier`: Optional request identifier

---

## Available Commands

### 1. Get OAuth2 Authorization URL

Generates and displays the authorization URL for starting the OAuth2 flow.

```sh
python -m tests.client get-oauth2-url --platform gmail
```

### 2. Exchange OAuth2 Code

Exchanges the authorization code for access and refresh tokens, decrypts the token, and stores the session data.

```sh
python -m tests.client exchange-oauth2-code --platform gmail --code <AUTH_CODE>
```

### 3. Sync Keys

Rotates client and server ephemeral key pools for a token. It uploads 256 new client ephemeral public keys, gets 256 new server public keys.

```sh
python -m tests.client sync-keys
```

> [!NOTE]
> If multiple tokens are stored, you will be prompted interactively to select one
> or you can specify the token using the `--token` argument.

### 4. Revoke OAuth2 Token

Revokes a stored OAuth2 token.

```sh
python -m tests.client revoke-oauth2-token
```

> [!NOTE]
> If multiple tokens are stored, you will be prompted interactively to select one
> or you can specify the token using the `--token` argument.

### 5. Get PNBA Code

Requests a passcode/OTP for Phone Number-Based Authentication (PNBA).

```sh
python -m tests.client get-pnba-code --platform telegram --phone-number +123456789
```

```sh
python -m tests.client get-pnba-code --platform telegram --phone-number +123456789 --auth-channel signal
```

### 6. Exchange PNBA Code

Exchanges the PNBA OTP code for a token, decrypts it, and stores the session data.

```sh
python -m tests.client exchange-pnba-code --platform telegram --phone-number +123456789 --code <OTP_CODE>
```

```sh
python -m tests.client exchange-pnba-code --platform telegram --phone-number +123456789 --code <OTP_CODE> --auth-channel signal
```

If the account has two-step verification enabled, re-run with `--password`:

```sh
python -m tests.client exchange-pnba-code --platform telegram --phone-number +123456789 --code <OTP_CODE> --password <PASSWORD>
```

### 7. Revoke PNBA Token

Revokes a stored PNBA token.

```sh
python -m tests.client revoke-pnba-token
```

> [!NOTE]
> If multiple tokens are stored, you will be prompted interactively to select one
> or you can specify the token using the `--token` argument.

### 8. Send

Encrypts a message and publishes it to a platform via the REST `POST /v1/publications` endpoint. Constructs and serializes a `V1Payloads` payload, encrypts the content, and POSTs it with the sender's phone number as the `address`.

For messages without attachments the payload is sent as a single request. For messages with attachments the payload is split into SMS-sized segments and sent sequentially with a configurable interval between each, simulating real-world multi-segment SMS delivery.

By default `send` uses the online, token-based flow (requires a prior OAuth2/PNBA token for the target platform). Pass `--offline` to use the offline-first encryption scheme instead, which does not require a prior token.

```sh
python -m tests.client send --platform gmail --address +237123456789 --to friend@example.com --subject "Hello" --body "Test message"
```

```sh
python -m tests.client send --platform telegram --address +237123456789 --to +237123456789 --body "Hi there"
```

**With attachment:**

```sh
python -m tests.client send --platform gmail --address +237123456789 --to friend@example.com --subject "Hello" --body "See attached" --attachment ./file.pdf
```

**With attachment, custom interval, and shuffled segment order:**

```sh
python -m tests.client send --platform gmail --address +237123456789 --to friend@example.com --subject "Hello" --body "See attached" --attachment ./file.pdf --interval 2.5 --shuffle
```

**Dry run (prints all segments without sending):**

```sh
python -m tests.client send --platform gmail --address +237123456789 --to friend@example.com --subject "Hello" --body "See attached" --attachment ./file.pdf --dry-run --shuffle
```

**Offline-first (no token required, rmail only):**

```sh
python -m tests.client send --offline --platform rmail --address +237123456789 --to friend@example.com --subject "Hello" --body "No token needed"
```

If the server has `OFFLINE_PUBLISH_SHARED_SECRET` set, pass the matching value with `--tag`, or the offline publish is discarded:

```sh
python -m tests.client send --offline --platform rmail --address +237123456789 --to friend@example.com --subject "Hello" --body "No token needed" --tag <SECRET>
```

**Arguments:**

| Argument | Required | Description |
| :--- | :--- | :--- |
| `--address` | Yes | Sender's phone number in E.164 format (e.g. `+237123456789`) |
| `--body` | Yes | Message body |
| `--to` | No | Recipient address (email or phone number). Required for email/messaging platforms. |
| `--subject` | No | Message subject. Email platforms only. |
| `--attachment` | No | Path to a file to attach. Triggers multi-segment SMS payload assembly. |
| `--interval` | No | Seconds between segment transmissions (default: `1.0`). |
| `--shuffle` | No | Send segments in random order to simulate out-of-order delivery. |
| `--token` | No | Raw token (base64) to use. Omit for interactive prompt. |
| `--dry-run` | No | Print all segments and their send order instead of transmitting. |
| `--offline` | No | Use the offline-first encryption scheme instead of the token-based flow. |
| `--tag` | No | Shared secret sent in the request's `tag` field. Required if the server has `OFFLINE_PUBLISH_SHARED_SECRET` set. |

> [!NOTE]
> Each online send consumes one ephemeral keypair. The used keypair is removed from local state after a successful publish. Run `sync-keys` to replenish the pool when it runs low. `--offline` sends do not consume ephemeral keypairs since they don't use a stored token.

> [!TIP]
> Use `--shuffle` together with `--dry-run` to inspect the randomised segment order before committing to a live send. This is useful for verifying that the server correctly reassembles out-of-order segments.
