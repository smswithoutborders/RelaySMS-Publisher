# SMTP Transport

Publishes RelaySMS payloads received by email. Incoming mails are picked up by polling a mailbox over IMAP (`smtp_listener.py`), authenticated, and queued for publication.

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

1. Poll `SMTP_IMAP_MAIL_FOLDER` (comma-separated, e.g. `INBOX,Spam`) for unseen mail via IMAP IDLE. Including Spam catches legitimate mail a provider misfiled.
2. Reject each email unless the sender is allow-listed and authenticated (see [Security](#-security)).
3. Parse the body as JSON and validate the payload.
4. Queue the payload for publication.
5. Delete every handled email in one batched call per folder, rather than one round trip each - keeps a mailbox with a large backlog from being slow to work through.

## Security

Two checks must both pass before a message is queued:

**Allowlist**: `SMTP_ALLOWED_SENDERS` is a comma-separated list of exact addresses and/or domains. Empty means nothing is allowed. A domain entry trusts *any* authenticated sender on that domain, since DKIM authenticates the domain, not the specific mailbox - use an exact address if only one sender should be trusted.

**Authentication**: SPF/DKIM aren't re-checked here (that would need the sender's connecting IP, which isn't available after the fact). Instead, the listener trusts the `Authentication-Results` header ([RFC 8601](https://www.rfc-editor.org/rfc/rfc8601)) already stamped by the mailbox's own receiving server, but only when its `authserv-id` matches `SMTP_TRUSTED_AUTHSERV_ID`; otherwise a sender could forge their own passing header. `SMTP_REQUIRE_DKIM`/`SMTP_REQUIRE_SPF` control which verdicts are required.

Set `SMTP_VERIFY_DKIM_INDEPENDENTLY=true` to additionally re-verify the DKIM signature against DNS ourselves, as defense-in-depth.

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
make smtp-listener-start
```

`scripts/run.sh` and the `relaysms-publisher-smtp.service` systemd unit also start it, conditionally on `SMTP_TRANSPORT_ENABLED`.
