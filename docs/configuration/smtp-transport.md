# SMTP transport

Use this when gateway clients relay payloads by email instead of HTTPS. The listener watches a mailbox over IMAP, checks each sender, and queues the payload for publication.

## Set it up

1. Create a mailbox that the gateway clients email, with IMAP access.
2. In `.env`, set `SMTP_IMAP_SERVER`, `SMTP_IMAP_USERNAME` and `SMTP_IMAP_PASSWORD`. To also watch a spam folder, set `SMTP_IMAP_MAIL_FOLDER`, such as `INBOX,Spam`.
3. Set `SMTP_ALLOWED_SENDERS` to the addresses the gateway clients send from ([allowlist](#allowlist)).
4. Set `SMTP_TRUSTED_AUTHSERV_ID` to the `authserv-id` the mailbox's server writes: the first word of the `Authentication-Results` header in a received email, such as `mx.google.com` ([authentication](#authentication)).
5. Set `SMTP_TRANSPORT_ENABLED=true`, then check and restart:

   ```bash
   sudo ./manage.sh check
   sudo ./manage.sh restart
   ```

[Settings reference](settings.md#smtp-transport) lists every `SMTP_*` setting.

## Check it

```bash
sudo ./manage.sh logs --unit smtp --no-follow --lines 20
```

You should see `Connected to mailbox <SMTP_IMAP_SERVER>`.

## How it works

1. Waits for unseen mail in `SMTP_IMAP_MAIL_FOLDER` with IMAP IDLE.
2. Rejects each email unless the sender is allowlisted and authenticated.
3. Parses the body as JSON and validates the payload.
4. Queues the payload for publication, tagged with protocol `smtp`. Whether offline payloads from email publish depends on [offline publishing](offline-publishing.md).
5. Deletes each handled email. An email that hits an unexpected error stays in the folder and is retried on the next cycle.

### Allowlist

`SMTP_ALLOWED_SENDERS` lists exact addresses and domains, comma-separated. Empty allows nothing.

> [!WARNING]
> A domain entry trusts every authenticated sender on that domain, since DKIM vouches for the domain, not the mailbox. List an exact address when only one sender should be trusted.

### Authentication

The listener can't re-check SPF, which needs the sender's IP. It reads the `Authentication-Results` header ([RFC 8601](https://www.rfc-editor.org/rfc/rfc8601)) that the mailbox's own server added, and only from the `authserv-id` in `SMTP_TRUSTED_AUTHSERV_ID`, since a sender can forge such a header from anyone else.

## Message format

The body of each email must be a JSON object:

```json
{
  "address": "5447c1f50558292bd9df723f9fdc0b06b892199c7dcfaad5164f2d94dfd3470a",
  "dialing_code": "237",
  "text": "<base64-encoded serialized payload>"
}
```

| Field | Type | Required | Description |
| --- | --- | --- | --- |
| `address` | string | Yes | Sender ID from the gateway client, or an E.164 phone number |
| `dialing_code` | string | No | Sender's country calling code, for publication stats |
| `text` | string | Yes | Base64-encoded serialized payload |

## Next steps

To publish offline payloads that arrive by email, allow `smtp` in [Offline publishing](offline-publishing.md).
