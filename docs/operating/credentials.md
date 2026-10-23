# Credentials and access

Credentials log in to the REST API's admin endpoints, each with its own scopes. One holding every scope is an administrator. The RelaySMS app and gateway clients need none.

## Create a credential

```bash
sudo ./publisher.sh creds create --username ops --administrator
sudo ./publisher.sh creds create --username analyst --scope stats:publications:read
```

> [!IMPORTANT]
> The password is printed only once.

Usernames are 3 to 32 lowercase letters, digits, `.`, `_` or `-`, starting with a letter or digit.

## Scopes

| Scope | Allows |
| --- | --- |
| `stats:publications:read` | Read publication stats, without failure reasons |
| `stats:publications:reasons` | See failure reasons in publication stats |
| `gc:read` | List gateway clients |
| `gc:write` | Add, change and remove gateway clients |
| `platforms:read` | List platform adapters |
| `platforms:write` | Change and remove platform adapters |
| `creds:read` | List credentials |
| `creds:write` | Add, change and remove credentials |
| `audit:read` | Read the [audit log](audit-log.md), for the areas your other scopes cover |

`sudo ./publisher.sh creds scopes` prints the same list. Each `:write` scope needs its `:read` scope, and `stats:publications:reasons` needs `stats:publications:read`. Installing, updating and configuring adapters over the API also needs an administrator.

## Commands

| Command | Does |
| --- | --- |
| `creds list` | Lists credentials |
| `creds set-scopes --username <NAME> --scope <SCOPE>` | Replaces a credential's scopes; repeat `--scope`, or pass `--administrator` |
| `creds reset-password --username <NAME>` | Prints a new password and ends the credential's web sessions |
| `creds disable --username <NAME>` | Blocks it and ends its web sessions |
| `creds enable --username <NAME>` | Lets it log in again |
| `creds revoke-sessions --username <NAME>` | Logs it out of every web session; HTTP Basic still works |
| `creds delete --username <NAME>` | Deletes it and its sessions, after asking; `--yes` skips the question |

Prefix each with `sudo ./publisher.sh`. Credentials with `creds:write` can do the same over the [REST API](../reference/rest-api.md#managing-credentials), within their own scopes.

## Logging in

- **Web session:** `POST /v1/auth/login`, then send the session cookie with every request (`credentials: "include"` in `fetch`). Logins and writes (`POST`, `PATCH`, `DELETE`) with the cookie must come from the API's own origin or one listed in `AUTH_WEB_ORIGINS`, on the same site as the API. A session ends after `AUTH_SESSION_IDLE_MINUTES` idle (30) or `AUTH_SESSION_MAX_HOURS` (12).
- **HTTP Basic:** the username and password on every request, such as `curl -u analyst:<PASSWORD> https://<HOST>/v1/stats/publications`.

Scope changes apply on the credential's next request. nginx allows 5 logins a minute per IP address, and 30 HTTP Basic requests a minute per IP address.

Settings: [REST API access](../configuration/settings.md#rest-api-access).
