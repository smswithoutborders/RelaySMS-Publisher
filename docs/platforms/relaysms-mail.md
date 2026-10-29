# RelaySMS Mail

The `rmail` adapter gives each user an email alias tied to their phone number, and sends email from it through [SimpleLogin](https://simplelogin.io). Users link with a code sent over a messaging app by [Shortmesh Authy](https://github.com/shortmesh/Authy-API). It's the adapter that publishes [offline payloads](../configuration/offline-publishing.md), each from a new random alias.

*Last checked against SimpleLogin, Shortmesh Authy and Google: 2026-10-22.*

## Requirements

- A SimpleLogin Premium account, which custom domains and sending to new contacts require
- A domain whose DNS you control
- An SMTP account allowed to send as your SimpleLogin mailbox address
- A self-hosted Shortmesh Authy, to send the login codes

## SimpleLogin

1. Sign up at [app.simplelogin.io](https://app.simplelogin.io). The signup address becomes your mailbox. To use another, add and verify it under [Mailboxes](https://app.simplelogin.io/dashboard/mailbox).
2. Add your domain, or a subdomain such as `mail.example.com`, under [Custom domains](https://app.simplelogin.io/dashboard/custom_domain).
3. Create the DNS records the domain's page lists: ownership TXT, MX, SPF, DKIM and DMARC. SimpleLogin marks the last three optional, but without them mail sent from aliases doesn't arrive.
4. Create an [API key](https://app.simplelogin.io/dashboard/api_key).

## SMTP

The adapter sends each message from your mailbox address over SMTP, and SimpleLogin relays it from the user's alias.

For a Gmail mailbox, use `smtp.gmail.com`, port `465`, the Gmail address, and an [app password](https://myaccount.google.com/apppasswords), which needs 2-Step Verification on the account.

## Shortmesh Authy

Run [Authy-API](https://github.com/shortmesh/Authy-API) with its Interface-API, then in the Interface-API's admin UI:

1. Under Devices, link the phone that sends the codes.
2. Under Tokens, create a token.

## Configure the adapter

This example uses a Gmail mailbox:

```bash
sudo ./publisher.sh platforms add \
  https://github.com/smswithoutborders/relaysms-mail-pnba-adapter
sudo ./publisher.sh platforms config set rmail \
  sl_primary_email=you@gmail.com sl_primary_domain=mail.example.com \
  smtp_host=smtp.gmail.com smtp_port=465 smtp_username=you@gmail.com \
  authy_base_url=https://authy.example.com authy_sender=+237600000000
sudo ./publisher.sh platforms config set rmail sl_api_key smtp_password authy_token
```

`sudo ./publisher.sh platforms config show rmail` lists the optional settings, such as alias prefixes.

## Check it

```bash
sudo ./publisher.sh platforms list --name rmail
```

You should see ✓ under Configured.

```bash
curl https://authy.example.com/api/v1/platforms
```

You should see the channels Authy can send codes on, such as `signal`.

## Troubleshooting

### `No mailbox for <EMAIL>`

`sl_primary_email` isn't a verified SimpleLogin mailbox.

### `No suffix available for hostname '<DOMAIN>'`

`sl_primary_domain` isn't a verified custom domain in SimpleLogin.

### Sending fails with an SMTP authentication error

For Gmail, use an app password, not the account password. A changed account password revokes app passwords.

### Recipients don't get the email

Check the domain's SPF, DKIM and DMARC records on its SimpleLogin page.

### SimpleLogin refuses to create a contact

The account isn't Premium.

### Users don't get a login code

Check that the sender device is linked and online, and that the channel the app sends, such as `signal`, appears at `<AUTHY_BASE_URL>/api/v1/platforms`.

## Next steps

[Register a gateway client](../gateway-clients/manage.md) to relay SMS to the Publisher.
