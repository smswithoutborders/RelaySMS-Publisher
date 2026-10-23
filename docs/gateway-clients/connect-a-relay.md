# Connecting a relay

A gateway client receives the SMS that people send and relays each payload to the Publisher's `POST /v1/publications`. Pick one:

| Gateway client | Runs on | Use it for |
| --- | --- | --- |
| [Deku SMS](https://f-droid.org/packages/com.afkanerd.deku/) | An Android phone with a SIM card | A local number, with no SMS provider |
| [RelaySMS-GatewayClient-Twilio](https://github.com/smswithoutborders/RelaySMS-GatewayClient-Twilio) | A server, behind a Twilio number | A number that doesn't depend on a phone staying online |

## Requirements

- The Publisher's REST API reachable over HTTPS, behind the [reverse proxy](../installation/reverse-proxy.md)
- The number [registered as a gateway client](manage.md), so the RelaySMS app lists it

## Deku SMS on Android

1. Install [Deku SMS](https://f-droid.org/packages/com.afkanerd.deku/) on the phone and make it the default SMS app.
2. In its gateway settings, forward incoming SMS to `https://<HOST>/v1/publications`.
3. Keep the phone powered, with mobile data or Wi-Fi.

## Twilio

1. Install [RelaySMS-GatewayClient-Twilio](https://github.com/smswithoutborders/RelaySMS-GatewayClient-Twilio) as its README describes. It can run on the Publisher's server, on its own subdomain such as `twilio.example.com`. Set `TWILIO_AUTH_TOKEN` from the Twilio console, and keep a copy of the generated `SENDER_HASH_KEY`: a new key gives every sender a new address.
2. In its `.env`, set `FORWARD_URLS_JSON=https://<HOST>/v1/publications`.
3. If the Publisher allows [offline publishing](../configuration/offline-publishing.md) over `https`, set `FORWARD_TAG` to its `OFFLINE_PUBLISH_SHARED_SECRET`.
4. In the Twilio console, under the number's Messaging > A message comes in, set `https://<RELAY_HOST>/twilio-sms` with `HTTP POST`.

## Check it

Send an SMS from the RelaySMS app to the number, then follow the worker's log on the Publisher:

```bash
sudo ./manage.sh logs --unit worker
```

You should see `Published via '<PLATFORM>'.` To test without a phone, the [reference client](../developers/reference-client.md#publishing) posts a payload the way a gateway client does.

## Next steps

- [Back up](../operating/backup-restore.md) `.env` and `data/`.
- [Harden the install](../operating/security-hardening.md) before announcing the number.
