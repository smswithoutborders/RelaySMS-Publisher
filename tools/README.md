# Reference Client

`tools/client.py` drives the gRPC and REST flows by hand, the way a phone app would. It keeps tokens and key pools in local state between runs.

```bash
pip install -r requirements.txt
python -m tools.client <COMMAND> [ARGS]
```

## Connection Options

| Option | Default | Does |
| --- | --- | --- |
| `--host`, `--port` | `127.0.0.1`, `6000` | gRPC server |
| `--tls` | off | Use TLS for gRPC |
| `--rest-api` | `http://localhost:16000` | REST API base URL |
| `--platform`, `-p` | | Platform name, such as `gmail` or `telegram` |
| `--phone-number` | | Phone number, for PNBA |
| `--request-identifier` | | Optional request identifier |

## Linking Accounts

| Command | Does |
| --- | --- |
| `get-oauth2-url` | Prints the OAuth2 authorization URL |
| `exchange-oauth2-code --code <CODE>` | Exchanges the code and stores the token |
| `revoke-oauth2-token` | Revokes a stored OAuth2 token |
| `get-pnba-code [--auth-channel signal]` | Requests a PNBA one-time code |
| `exchange-pnba-code --code <CODE> [--password <PASSWORD>]` | Exchanges the code and stores the token; `--password` for two-step verification |
| `revoke-pnba-token` | Revokes a stored PNBA token |
| `sync-keys` | Replaces the token's 256 client and 256 server ephemeral keys |

```bash
python -m tools.client get-oauth2-url --platform gmail
python -m tools.client exchange-oauth2-code --platform gmail --code <AUTH_CODE>
python -m tools.client get-pnba-code --platform telegram --phone-number +237123456789
python -m tools.client exchange-pnba-code --platform telegram --phone-number +237123456789 --code <OTP>
```

> [!NOTE]
> With several stored tokens, `sync-keys` and the revoke commands ask which one to use. Pass `--token` to choose up front.

## Publishing

`send` encrypts a message and posts it to `POST /v1/publications` with `--address` as the sender. Without an attachment it's one request; with one, the payload is split into SMS-sized segments sent `--interval` seconds apart.

```bash
python -m tools.client send --platform gmail --address +237123456789 \
    --to friend@example.com --subject "Hello" --body "Test message"

python -m tools.client send --platform gmail --address +237123456789 \
    --to friend@example.com --subject "Hello" --body "See attached" --attachment ./file.pdf --interval 2.5 --shuffle

python -m tools.client send --offline --platform rmail --address +237123456789 \
    --to friend@example.com --subject "Hello" --body "No token needed" --tag <SECRET>
```

| Option | Does |
| --- | --- |
| `--address` | Sender's number in E.164 format (required) |
| `--body` | Message body (required) |
| `--to` | Recipient email or number, for email and messaging platforms |
| `--subject` | Subject, for email platforms |
| `--attachment` | File to attach, sent as several segments |
| `--interval` | Seconds between segments (default `1.0`) |
| `--shuffle` | Sends segments out of order |
| `--dry-run` | Prints the segments and their order without sending |
| `--token` | Raw token (base64), instead of choosing interactively |
| `--offline` | Uses offline-first encryption, which needs no linked token (`rmail` only) |
| `--tag` | The server's `OFFLINE_PUBLISH_SHARED_SECRET`, when it sets one |

> [!NOTE]
> Each online send uses up one ephemeral key pair. Run `sync-keys` when the pool runs low. Offline sends use none.

> [!TIP]
> `--shuffle --dry-run` shows the segment order before a live send, to check the server reassembles out-of-order segments.
