# Gmail

Lets users send email from their Gmail account.

*Last checked against Google Cloud Console: 2026-10-22.*

## Requirements

- A Google Cloud account
- An HTTPS [redirect URI](manage.md#redirect-uris)

## Create the OAuth client

1. [Create a project](https://console.cloud.google.com/projectcreate), or pick one.
2. [Enable the Gmail API](https://console.cloud.google.com/apis/library/gmail.googleapis.com).
3. In Google Auth Platform > [Branding](https://console.cloud.google.com/auth/branding), click **Get started**.
4. Enter the app name, support email and contact email. Choose **External** as the audience, unless every user belongs to your Google Workspace organization.
5. In [Data Access](https://console.cloud.google.com/auth/scopes), add these scopes and save:
   - `openid`
   - `https://www.googleapis.com/auth/userinfo.email`
   - `https://www.googleapis.com/auth/userinfo.profile`
   - `https://www.googleapis.com/auth/gmail.send`
6. In [Clients](https://console.cloud.google.com/auth/clients), create a client of type **Web application**.
7. Under Authorized redirect URIs, add every redirect URI your apps send, the default first, and create the client.
8. Download the client's JSON from the dialog that confirms it.

> [!IMPORTANT]
> Google shows the client secret only at creation. If you close the dialog without downloading the JSON, add a new secret to the client.

## Configure the adapter

Copy the JSON to the server, then:

```bash
sudo ./publisher.sh platforms add \
  https://github.com/smswithoutborders/gmail-oauth2-adapter
sudo ./publisher.sh platforms setup gmail \
  --input client_file=@/tmp/client_secret_<ID>.apps.googleusercontent.com.json
```

`setup` copies the client ID, secret and redirect URIs from the file.

To add a redirect URI later, add it to the client in the console, then set the whole list:

```bash
sudo ./publisher.sh platforms config set gmail \
  redirect_uris=https://a.example.com/callback,https://b.example.com/callback
```

## Check it

```bash
sudo ./publisher.sh platforms config show gmail
```

You should see `redirect_uris` in the client's order, and `client_secret` as `(secret, set)`.

## Testing and production

| Publishing status | Who can link | Limits |
| --- | --- | --- |
| Testing | Test users listed under [Audience](https://console.cloud.google.com/auth/audience) | Links expire after 7 days |
| In production, unverified | Anyone, after a warning | 100 users in all |
| In production, verified | Anyone | None |

`gmail.send` is a sensitive scope, so [verification](https://developers.google.com/identity/protocols/oauth2/production-readiness/sensitive-scope-verification) needs:

- the redirect and home page domains verified in Google Search Console;
- a public home page and a privacy policy on that domain, describing how the app uses Gmail;
- a justification for each scope;
- an unlisted YouTube video showing the consent screen and how the app sends email.

Publish the app under Audience, then submit it in the [Verification Center](https://console.cloud.google.com/auth/verification).

## Troubleshooting

### `setup` fails with `redirect_uris is required`

The client has no authorized redirect URIs. Add them in the console, then set them with `config set gmail redirect_uris=...`.

### `redirect_uri_mismatch`

The URI the app sent isn't on the client. Add it exactly, trailing slash included.

### Linking fails with `Access wasn't granted to ...`

The user unticked a permission on the consent screen. They should link again and allow every permission.

### Sending fails with `Google refused the refresh token`

Links made while the app is in Testing expire after 7 days. Publish the app, and have users link again.

### The client disappeared

Google deletes clients unused for 6 months. Restore it within 30 days, or create a new one.

## Next steps

[Register a gateway client](../gateway-clients/manage.md) to relay SMS to the Publisher.
