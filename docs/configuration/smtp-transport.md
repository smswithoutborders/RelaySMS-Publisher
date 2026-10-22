# SMTP transport

Publishes RelaySMS payloads that gateway clients send by email. The listener watches a mailbox over IMAP, checks each sender, and queues the payload for publication.

## Message format

The body of each email must be a JSON object:

```json
{
  "address": "5447c1f50558292bd9df723f9fdc0b06b892199c7dcfaad5164f2d94dfd3470a",
  "dialing_code": "237",
  "text": "<base64-encoded serialized payload>"
}
```

| Field | Type | Description |
| :--- | :--- | :--- |
| address | string | Sender ID from the gateway client, or an E.164 phone number |
| dialing_code | string | Optional. Sender's country calling code, for publication stats |
| text | string | Base64-encoded serialized payload |

## How it works

1. Waits for unseen mail in `SMTP_IMAP_MAIL_FOLDER` with IMAP IDLE. List several folders, such as `INBOX,Spam`, to catch mail a provider misfiled.
2. Rejects each email unless the sender is allowlisted and authenticated (see [Security](#security)).
3. Parses the body as JSON and validates the payload.
4. Queues the payload for publication.
5. Deletes each handled email. An email that hits an unexpected error stays in the folder and is retried on the next cycle.

## Security

Two checks must both pass before a message is queued:

**Allowlist:** `SMTP_ALLOWED_SENDERS` lists exact addresses and domains, comma-separated. Empty allows nothing.

> [!WARNING]
> A domain entry trusts every authenticated sender on that domain, since DKIM vouches for the domain, not the mailbox. List an exact address when only one sender should be trusted.

**Authentication:** the listener can't re-check SPF, which needs the sender's IP. It reads the `Authentication-Results` header ([RFC 8601](https://www.rfc-editor.org/rfc/rfc8601)) that the mailbox's own server added, and only from the `authserv-id` in `SMTP_TRUSTED_AUTHSERV_ID`, since a sender can forge such a header from anyone else. `SMTP_REQUIRE_DKIM` and `SMTP_REQUIRE_SPF` choose the verdicts required. `SMTP_VERIFY_DKIM_INDEPENDENTLY=true` also re-verifies the DKIM signature against DNS.

## Configuration

Settings: [SMTP transport](settings.md#smtp-transport).

The listener tags what it queues with protocol `smtp`. Whether offline payloads from email publish depends on [offline publishing](offline-publishing.md).

## Running

Set `SMTP_TRANSPORT_ENABLED=true`, then run `sudo ./manage.sh restart`. The `relaysms-publisher-smtp` service runs the listener and exits at once while the setting is off.
