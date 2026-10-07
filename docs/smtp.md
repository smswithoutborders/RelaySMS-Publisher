# SMTP Transport

Publishes RelaySMS payloads received by email. Incoming mails are picked up by polling a mailbox over IMAP (`publisher/smtp/listener.py`), authenticated, and queued for publication.

## Message Format

The body of each email must be a JSON object:

```json
{
  "address": "+12025550123",
  "text": "<base64-encoded serialized payload>"
}
```

| Field | Type | Description |
| :--- | :--- | :--- |
| address | string | Sender phone number in E.164 format |
| text | string | Base64-encoded serialized payload |

## How It Works

1. Waits for unseen mail in `SMTP_IMAP_MAIL_FOLDER` with IMAP IDLE. List several folders, such as `INBOX,Spam`, to catch mail a provider misfiled.
2. Rejects each email unless the sender is allowlisted and authenticated (see [Security](#security)).
3. Parses the body as JSON and validates the payload.
4. Queues the payload for publication.
5. Deletes the handled emails, in one call per folder.

## Security

Two checks must both pass before a message is queued:

**Allowlist:** `SMTP_ALLOWED_SENDERS` lists exact addresses and domains, comma-separated. Empty allows nothing.

> [!WARNING]
> A domain entry trusts every authenticated sender on that domain, since DKIM vouches for the domain, not the mailbox. List an exact address when only one sender should be trusted.

**Authentication:** the listener can't re-check SPF, which needs the sender's IP. It reads the `Authentication-Results` header ([RFC 8601](https://www.rfc-editor.org/rfc/rfc8601)) that the mailbox's own server added, and only from the `authserv-id` in `SMTP_TRUSTED_AUTHSERV_ID`, since a sender can forge such a header from anyone else. `SMTP_REQUIRE_DKIM` and `SMTP_REQUIRE_SPF` choose the verdicts required. `SMTP_VERIFY_DKIM_INDEPENDENTLY=true` also re-verifies the DKIM signature against DNS.

## Configuration

| Variable | Default | Description |
| :--- | :--- | :--- |
| `SMTP_TRANSPORT_ENABLED` | `false` | Enables the listener. |
| `SMTP_IMAP_SERVER` | - | IMAP host. Required when enabled. |
| `SMTP_IMAP_PORT` | `993` | IMAP port. |
| `SMTP_IMAP_USERNAME` | - | Required when enabled. |
| `SMTP_IMAP_PASSWORD` | - | Required when enabled. |
| `SMTP_IMAP_MAIL_FOLDER` | `INBOX` | Comma-separated folders to poll. |
| `SMTP_TLS_CLIENT_CERTIFICATE` / `SMTP_TLS_CLIENT_KEY` | - | Optional mTLS client cert, only if the provider requires one. |
| `SMTP_ALLOWED_SENDERS` | - | Comma-separated allowlist of addresses and/or domains. |
| `SMTP_TRUSTED_AUTHSERV_ID` | - | `authserv-id` whose `Authentication-Results` verdicts are trusted. |
| `SMTP_REQUIRE_DKIM` | `true` | Require `dkim=pass`. |
| `SMTP_REQUIRE_SPF` | `true` | Require `spf=pass`. |
| `SMTP_VERIFY_DKIM_INDEPENDENTLY` | `false` | Also re-verify the DKIM signature via DNS. |
| `OFFLINE_PUBLISH_ALLOWED_PROTOCOLS` | - | Comma-separated allowlist of protocols allowed to publish offline payloads. Messages queued by this listener are tagged `smtp`; if set and `smtp` isn't listed, offline payloads from email are discarded. |

## Running

```sh
python3 -m publisher.smtp
```

`scripts/run.sh` and the `relaysms-publisher-smtp` unit start it too; it exits at once while `SMTP_TRANSPORT_ENABLED` is off.
