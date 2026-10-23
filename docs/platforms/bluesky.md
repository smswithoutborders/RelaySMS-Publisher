# Bluesky

Lets users post to Bluesky. Bluesky has no app registration: the Publisher serves the client's metadata at a public URL, and that URL is the client ID.

*Last checked against the AT Protocol OAuth spec: 2026-10-22.*

## Requirements

- The REST API is public over HTTPS on port 443, behind the [reverse proxy](../installation/reverse-proxy.md).
- `https://<HOST>/v1/platforms/bluesky/oauth/client-metadata.json` answers `200` with JSON, with no redirect on the way. It does while the adapter is enabled.
- The [redirect URIs](manage.md#redirect-uris) use HTTPS.

## Configure the adapter

```bash
sudo ./publisher.sh platforms add \
  https://github.com/smswithoutborders/bluesky-oauth2-adapter
sudo ./publisher.sh platforms config set bluesky \
  client_id=https://publisher.example.com/v1/platforms/bluesky/oauth/client-metadata.json \
  client_uri=https://publisher.example.com \
  client_name=RelaySMS \
  redirect_uris=https://example.com/callback \
  "scope=atproto transition:generic"
```

| Setting | Required | Description |
| --- | --- | --- |
| `client_id` | Yes | The metadata URL above, exactly as the Publisher serves it |
| `client_uri` | Yes | Home page on the Publisher's host, the same host as `client_id` |
| `client_name` | Yes | Name on Bluesky's consent page |
| `redirect_uris` | Yes | Comma-separated redirect URIs your apps send, the default first |
| `scope` | Yes | `atproto transition:generic` |
| `pds_url` | No | Auth server. Default: `https://bsky.social` |

## Check it

```bash
curl -i https://publisher.example.com/v1/platforms/bluesky/oauth/client-metadata.json
```

You should see `200` and JSON whose `client_id` equals the URL you fetched.

## Troubleshooting

### Bluesky says the client metadata is invalid

`client_id` must match the served URL exactly: `https`, `/v1`, no trailing slash.

### The metadata URL redirects or needs a login

Bluesky refuses redirects. Serve the URL directly over HTTPS.

### `Access wasn't granted to every scope.`

Set `scope` to exactly `atproto transition:generic`.

### `The account uses a different auth server.`

The account isn't on `pds_url`'s auth server, such as one on a self-hosted PDS. Only accounts there can link.

### A changed redirect URI isn't accepted yet

Bluesky's auth server caches the metadata. Try again later.

## Next steps

[Register a gateway client](../gateway-clients/manage.md) to relay SMS to the Publisher.
