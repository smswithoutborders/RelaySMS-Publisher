# Requirements

- **Operating system**: Ubuntu 24.04 or Debian 13, or any Linux host with Docker.
- **Python**: 3.12 or newer. The installer installs it, with the other system packages and Rust.
- **Database**: SQLite (the default) or a database server. See [Database](database.md) for the supported ones.
- **Domain**: a DNS name pointing at the server, for the TLS certificate. See [Reverse proxy and TLS](reverse-proxy.md).
- **Inbound ports (firewall)**: 80 and 443 for nginx. On a server install, the services listen on `127.0.0.1` only. Docker publishes `PORT` (16000) and `GRPC_PORT` (6000).
- **Outbound access**: `github.com`, `pypi.org`, the Rust installer and the system's package mirrors to install the Publisher and its adapters; Let's Encrypt for certificates; each platform's API to publish.
- **Platform credentials**: from each platform you offer, such as a Google Cloud OAuth client for Gmail. See [Provider guides](../platforms/manage.md#provider-guides).
- **Gateway client**: at least one phone number that relays SMS, such as an Android phone running Deku SMS. See [Connecting a relay](../gateway-clients/connect-a-relay.md).
