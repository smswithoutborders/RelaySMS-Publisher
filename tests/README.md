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

### 6. Exchange PNBA Code

Exchanges the PNBA OTP code for a token, decrypts it, and stores the session data.

```sh
python -m tests.client exchange-pnba-code --platform telegram --phone-number +123456789 --code <OTP_CODE>
```

### 7. Revoke PNBA Token

Revokes a stored PNBA token.

```sh
python -m tests.client revoke-pnba-token
```

> [!NOTE]
> If multiple tokens are stored, you will be prompted interactively to select one
> or you can specify the token using the `--token` argument.
