# RelaySMS Publisher

The Publisher posts to online platforms (Gmail, Telegram, Mastodon and more) from content people send by SMS, so they can publish without an internet connection.

## How it works

```mermaid
flowchart TB
    app["RelaySMS app"]
    gateway["Gateway client"]
    mailbox["Mailbox"]
    platform["Gmail, Telegram, ..."]

    subgraph publisher["Publisher"]
        grpc["gRPC API"]
        rest["REST API"]
        smtp["Email listener"]
        worker["Celery worker"]
        adapter["Platform adapter"]
    end

    app -- "link an account, online" --> grpc
    app -- "encrypted SMS" --> gateway
    gateway -- "HTTPS" --> rest
    gateway -- "email" --> mailbox
    smtp -- "IMAP" --> mailbox
    rest --> worker
    smtp --> worker
    grpc --> adapter
    worker --> adapter
    adapter --> platform
```

1. While online, a user links an account through the gRPC API. The Publisher stores its token encrypted.
2. Offline, the app encrypts the content and sends it by SMS to a gateway client, a phone number that relays SMS.
3. The gateway client posts the payload to the REST API, or emails it to a mailbox the Publisher reads.
4. A Celery worker decrypts the payload and publishes it through the platform's adapter.

## Where to start

| To | Read |
| --- | --- |
| Try the Publisher on your machine | [Quick start](getting-started/quick-start.md) |
| Run it in production | [Requirements](installation/requirements.md), then [Install on a server](installation/server.md) |
| Offer a platform | [Managing adapters](platforms/manage.md) |
| Relay SMS to the Publisher | [Managing gateway clients](gateway-clients/manage.md) |
| Build a client | [gRPC API](reference/grpc-api.md) and [REST API](reference/rest-api.md) |
| Understand the protocol | [RelaySMS whitepaper](explanation/relaysms-whitepaper.pdf) |
