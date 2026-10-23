# Security hardening

A server install listens on `127.0.0.1` only, runs each service under systemd sandboxing with everything read-only except its data directories, and sits behind nginx with TLS and rate limits. These steps close what's left to you.

## Network and firewall

1. Allow only SSH, HTTP and HTTPS in:

   ```bash
   sudo ufw allow OpenSSH
   sudo ufw allow 'Nginx Full'
   sudo ufw enable
   ```

2. Keep `HOST` and `GRPC_HOST` at `127.0.0.1`, so only nginx reaches the services.
3. On Docker, bind `PORT` and `GRPC_PORT` to `127.0.0.1` in `docker-compose.yml`, since Docker's published ports bypass ufw, and put nginx in front ([details](../installation/docker.md)).

## Service user

The services run as the user who ran the installer with `sudo`, or as a new `relaysms` user when it ran from a root shell. For a dedicated user with no login or `sudo` rights, run the installer from a root shell (`sudo -i`). Changing it on an existing install means reinstalling.

## Settings

| Setting | Keep it at |
| --- | --- |
| `API_DOCS_ENABLED` | `false` in production |
| `AUTH_SESSION_COOKIE_SECURE` | `true` |
| `AUTH_WEB_ORIGINS` | Only the web client origins you run |
| `PLATFORMS_GITHUB_ORGS` | Only orgs you trust: installing an adapter runs its code on the server |
| `SMTP_ALLOWED_SENDERS` | Exact addresses; a domain trusts every sender on it ([details](../configuration/smtp-transport.md#allowlist)) |
| `DATABASE_ENCRYPTION_ENABLED`, `DATABASE_FIELD_ENCRYPTION_ENABLED` | `true` |

## Credentials

Give each person their own [credential](credentials.md), with only the scopes they need. Review the [audit log](audit-log.md) for `denied` events (a change beyond the actor's scopes) and `failed` ones (a refused login).
