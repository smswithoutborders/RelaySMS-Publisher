# Mastodon

Lets users post to Mastodon. The adapter's setup registers the app on a Mastodon server, so there's no console to visit.

*Last checked against the Mastodon API: 2026-10-22.*

## Requirements

- A Mastodon server running 4.4 or newer: see `version` at `https://<SERVER>/api/v2/instance`
- An HTTPS [redirect URI](manage.md#redirect-uris)

The adapter serves one Mastodon server: only accounts on that server can link.

## Configure the adapter

```bash
sudo ./publisher.sh platforms add \
  https://github.com/smswithoutborders/mastodon-oauth2-adapter
sudo ./publisher.sh platforms setup mastodon \
  --input client_name=RelaySMS \
  --input redirect_uris=https://example.com/callback \
  --input website=https://example.com \
  --input base_url=https://mastodon.social
```

| Input | Required | Description |
| --- | --- | --- |
| `client_name` | Yes | App name on the server's consent page |
| `redirect_uris` | Yes | Comma-separated redirect URIs your apps send, the default first |
| `website` | No | Home page on the consent page |
| `base_url` | No | The server. Default: `https://mastodon.social` |

`setup` registers the app with the scopes `profile`, `write:statuses` and `write:media`, and saves its client ID and secret. Run it again to change the redirect URIs or the server. It registers a new app and replaces every setting. After changing the server, users must link again.

## Check it

```bash
sudo ./publisher.sh platforms config show mastodon
```

You should see `client_secret` as `(secret, set)`.

## Troubleshooting

### A user can't link

Their account is on another server than `base_url`.

### Linking fails after authorizing

The server runs Mastodon older than 4.4.

### "The redirect URI included is not valid"

The app sent a URI the app registration doesn't have. Run `setup` again with it.

## Next steps

[Register a gateway client](../gateway-clients/manage.md) to relay SMS to the Publisher.
