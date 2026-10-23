# RelaySMS Publisher

The Publisher posts to online platforms (Gmail, Telegram, Mastodon and more) from content people send by SMS, so they can publish without an internet connection.

## How it works

```mermaid
---
config:
  flowchart:
    curve: linear
---
flowchart TB
    app["RelaySMS app"]
    gateway["Gateway client"]
    platform["Gmail, Telegram, ..."]

    subgraph publisher[" "]
        grpc["gRPC API"]
        rest["REST API"]
        smtp["Email listener"]
        worker["Celery worker"]
        adapter["Platform adapter"]
    end

    app -- "link an account, online" --> grpc
    app -- "encrypted SMS" --> gateway
    gateway -- "HTTPS" --> rest
    gateway -- "email, via a mailbox" --> smtp
    rest --> worker
    smtp --> worker
    grpc --> adapter
    worker --> adapter
    adapter --> platform
```

The shaded box is the Publisher.

1. While online, a user links an account through the gRPC API. The Publisher stores its token encrypted.
2. Offline, the app encrypts the content and sends it by SMS to a gateway client, a phone number that relays SMS.
3. The gateway client posts the payload to the REST API, or emails it to a mailbox the Publisher reads.
4. A Celery worker decrypts the payload and publishes it through the platform's adapter.

## Key terms

- **Gateway client**: a phone number that relays SMS to the Publisher, from an Android phone running Deku SMS or from Twilio. See [Connecting a relay](gateway-clients/connect-a-relay.md).
- **Adapter** (platform adapter): the plugin that publishes to one platform, such as Gmail, installed from its own repository. See [Managing adapters](platforms/manage.md).
- **Linked account**: a user's account on a platform, authorized once while online. The Publisher stores its token encrypted.
- **OAuth2 and PNBA**: the two ways an account links. OAuth2 goes through the platform's consent page (Gmail, Mastodon, Bluesky). Phone number-based authentication (PNBA) uses a code sent to the user's phone (Telegram, RelaySMS Mail).
- **Offline payload**: content sent without a linked account, published through [RelaySMS Mail](platforms/relaysms-mail.md).

The [glossary](reference/glossary.md) defines the rest, and [Architecture](explanation/architecture.md) shows every component.

## Where to start

| To | Read |
| --- | --- |
| Try the Publisher on your machine | [Quick start](getting-started/quick-start.md) |
| Run it in production | [Requirements](installation/requirements.md), then [Install on a server](installation/server.md) |
| Offer a platform | [Managing adapters](platforms/manage.md) |
| Relay SMS to the Publisher | [Managing gateway clients](gateway-clients/manage.md) |
| Build a client | [gRPC API](reference/grpc-api.md) and [REST API](reference/rest-api.md) |
| Understand the protocol | [Security model](explanation/security-model.md) and the [RelaySMS whitepaper](explanation/relaysms-whitepaper.pdf) |

## Getting help

- Ask questions and report bugs in the [issue tracker](https://github.com/smswithoutborders/RelaySMS-Publisher/issues); [CONTRIBUTING.md](https://github.com/smswithoutborders/RelaySMS-Publisher/blob/main/CONTRIBUTING.md#ways-to-contribute) says what a useful report has.
- Report vulnerabilities privately, as [SECURITY.md](https://github.com/smswithoutborders/RelaySMS-Publisher/blob/main/SECURITY.md) describes.
