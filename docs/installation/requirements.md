# Requirements

| Need | Details |
| --- | --- |
| Operating system | Ubuntu 24.04 or Debian 13, or any Linux host with Docker |
| Python | 3.12 or newer. The installer installs it, with the other system packages and Rust. |
| Database | SQLite (the default), MySQL 8.0.28 or newer, MariaDB, or PostgreSQL 12 or newer. See [Database](database.md). |
| Domain | A DNS name pointing at the server, for the TLS certificate. See [Reverse proxy and TLS](reverse-proxy.md). |
| Inbound ports | 80 and 443 for nginx. On a server install, the services listen on `127.0.0.1` only. |
| Outbound access | `github.com`, `pypi.org`, the Rust installer and the system's package mirrors to install the Publisher and its adapters; Let's Encrypt for certificates; each platform's API to publish |
| Platform credentials | From each platform you offer, e.g. a Google Cloud OAuth client for Gmail. See [Managing adapters](../platforms/manage.md). |
| Gateway client | At least one phone number that relays SMS to the REST API or a mailbox. See [Managing gateway clients](../gateway-clients/manage.md). |
