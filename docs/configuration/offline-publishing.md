# Offline publishing

Offline payloads let people send email through [RelaySMS Mail](../platforms/relaysms-mail.md) without linking an account; linked accounts need none of this ([settings](settings.md#offline-publishing)). The app encrypts an offline payload to the server's identity key, and the Publisher publishes it through the `rmail` adapter, which must be installed. Anyone who can reach an allowed protocol can send one.

Each payload is tagged with the protocol it arrived on:

- `https`: [REST `POST /v1/publications`](../reference/rest-api.md#publishing)
- `smtp`: the [SMTP transport](smtp-transport.md)

- An offline payload from a protocol not in `OFFLINE_PUBLISH_ALLOWED_PROTOCOLS` is discarded.
- An offline payload over `https` must carry `OFFLINE_PUBLISH_SHARED_SECRET` in the request's `tag` field, or it's discarded.
- Leaving `OFFLINE_PUBLISH_ALLOWED_PROTOCOLS` empty, or listing `https`, without the secret fails `manage.sh check`, and the services refuse to start.
- A discarded payload is logged and recorded as `rejected` in the publication stats, with reason `protocol_not_allowed`, `offline_tag_missing` or `offline_tag_invalid`. `POST /v1/publications` still returns success, since the check runs in the queue.

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

## Next steps

[Connect each relay](../gateway-clients/connect-a-relay.md) that posts over `https` with the secret as its `tag` (`FORWARD_TAG` for Twilio).
