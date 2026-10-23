# Audit log

The Publisher records every change to credentials, adapters and gateway clients, every web login and every refused login, whether made over the REST API or the CLI. Read it at `GET /v1/audit-events`:

```bash
curl -u ops:<PASSWORD> https://<HOST>/v1/audit-events
```

It needs `audit:read`, plus the read scope of each area: `creds:read` for `auth.*` and `creds.*` events, `platforms:read` for `platforms.*`, `gc:read` for `gateway_clients.*`. Events from areas you can't read are left out. Filter with `action`, `actor`, `target`, `since` and `until`, such as `?action=auth.login&since=2026-10-01`. Results are [paginated](../reference/rest-api.md#pagination).

## Events

| Action | Recorded when |
| --- | --- |
| `creds.create`, `creds.update`, `creds.reset_password`, `creds.revoke_sessions`, `creds.delete` | A credential changes. `details` says what changed, never secrets. |
| `auth.login` | A web session starts, or a web or HTTP Basic login for an existing username is refused |
| `auth.logout` | A web session ends |
| `platforms.add`, `platforms.update`, `platforms.remove` | An adapter is installed, updated or removed. `details` has the source URL and commits. |
| `platforms.enable`, `platforms.disable` | An adapter is offered to users again, or hidden from them |
| `platforms.configure`, `platforms.setup` | An adapter's settings change. `details` has the keys saved. |
| `gateway_clients.create`, `gateway_clients.update`, `gateway_clients.delete` | A gateway client changes. `details` has its fields, or what changed. |
| `gateway_clients.enable`, `gateway_clients.disable` | A gateway client is listed publicly again, or hidden |

## Fields

- `outcome`: `success`, `denied` (the change went beyond the actor's scopes) or `failed` (a refused login for an existing username: wrong password, or disabled).
- `actor`: the username at the time; null for the CLI or a failed login.
- `details`: what changed, never secrets; for `auth.login`, `method` is `session` or `basic`.

Successful HTTP Basic requests aren't recorded. Events are kept for `AUDIT_RETENTION_DAYS` ([Retention](../configuration/settings.md#retention)).
