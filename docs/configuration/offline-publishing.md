# Offline publishing

Use this to let people send email through [RelaySMS Mail](../platforms/relaysms-mail.md) without linking an account first. Payloads from linked accounts, such as Gmail ones, need none of these settings. An offline payload carries no linked account: the app encrypts it to the server's identity key, and the Publisher publishes it through the RelaySMS Mail adapter (`rmail`), which must be installed. Anyone who can reach an allowed protocol can send one.

Each payload is tagged with the protocol it arrived on:

- `https`: [REST `POST /v1/publications`](../reference/rest-api.md#publishing)
- `smtp`: the [SMTP transport](smtp-transport.md)

Settings: [Offline publishing](settings.md#offline-publishing).

- An offline payload from a protocol not in `OFFLINE_PUBLISH_ALLOWED_PROTOCOLS` is discarded.
- An offline payload over `https` must carry `OFFLINE_PUBLISH_SHARED_SECRET` in the request's `tag` field, or it's discarded.
- Leaving `OFFLINE_PUBLISH_ALLOWED_PROTOCOLS` empty, or listing `https`, without the secret fails `manage.sh check`, and the services refuse to start.
- A discarded payload is logged and recorded as `failed` in the publication stats, with reason `protocol_not_allowed`, `offline_tag_missing` or `offline_tag_invalid`. `POST /v1/publications` still returns success, since the check runs in the queue.

## Allowing https

1. Generate a secret:

   ```bash
   openssl rand -hex 32
   ```

2. Set `OFFLINE_PUBLISH_SHARED_SECRET` to it, and add `https` to `OFFLINE_PUBLISH_ALLOWED_PROTOCOLS`, such as `smtp,https`.
3. Check and restart:

   ```bash
   sudo ./manage.sh check
   sudo ./manage.sh restart
   ```

4. Give the secret to each gateway client that posts to `POST /v1/publications`, to send as `tag`.

For a Twilio number, [RelaySMS-GatewayClient-Twilio](https://github.com/smswithoutborders/RelaySMS-GatewayClient-Twilio) can post to this server: set its `FORWARD_URLS_JSON` to `https://<host>/v1/publications` and `FORWARD_TAG` to the secret.
