# Telegram

Lets users send Telegram messages. Users link with their phone number, a login code and, if they set one, their two-step verification password.

*Last checked against my.telegram.org: 2026-10-22.*

## Requirements

- Agreement to Telegram's [API terms of service](https://core.telegram.org/api/terms)
- A Telegram account made with an official app, on a phone number you'll keep. Each number can create only one API ID.

## Get the API ID and hash

1. Sign in at [my.telegram.org](https://my.telegram.org) with the number in international format. The login code arrives in the Telegram app, not by SMS.
2. Open **API development tools**.
3. Fill in the app title and a short name (5 to 32 letters and digits), and create the application.
4. Copy the **App api_id** and **App api_hash**.

The hash can't be changed: replacing a leaked one takes a new app on another number.

## Configure the adapter

```bash
sudo ./publisher.sh platforms add \
  https://github.com/smswithoutborders/telegram-pnba-adapter
sudo ./publisher.sh platforms config set telegram api_id=<API_ID> api_hash
```

## Check it

```bash
sudo ./publisher.sh platforms list --name telegram
```

You should see ✓ under Configured.

## Troubleshooting

### The form at my.telegram.org says only "ERROR"

Try again later from a home connection without a VPN, in a private window.

### A user's account is limited or banned

Heavy or spam-like sending gets accounts banned. Appeals go to recover@telegram.org.

## Next steps

[Register a gateway client](../gateway-clients/manage.md) to relay SMS to the Publisher.
