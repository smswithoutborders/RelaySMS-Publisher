# Publisher REST API

The REST API serves platform, gateway client and server key metadata, accepts encrypted payloads for publishing, and lets credentials read stats, manage credentials and read the audit log.

The endpoint reference is [openapi.json](openapi.json), generated from the app. Open it in any OpenAPI viewer, or set `API_DOCS_ENABLED=true` on a dev server and browse `/docs`. After changing an endpoint, run `make docs`; a test fails while the file is stale.

This page covers what the reference doesn't show well.

## Base URL

```
https://<host>/v1
```

`/health` is the only endpoint outside `/v1`.

## Authentication

Credentials and their scopes are managed with [`./publisher.sh creds`](../README.md#credentials) or the `/v1/creds` endpoints.

* **Web session:** `POST /v1/auth/login`, then send the cookie with every request (`credentials: "include"` in `fetch`). Writes (`POST`, `PATCH`, `DELETE`) with the cookie must come from this API's origin or `AUTH_WEB_ORIGINS`. Sessions end after 30 minutes idle or 12 hours.
* **HTTP Basic:** username and password on every request, e.g. `curl -u analyst:<password> .../v1/stats/publications`. HTTPS only.

Scope changes apply on the credential's next request. Each endpoint's description names the scopes it needs.

## Managing Credentials

A credential can only grant scopes it holds, can't change itself, and can't change a credential holding scopes it lacks. These return `403`.

`GET /v1/creds/{username}` returns an opaque `ETag`. Send it back unchanged as `If-Match` to change, reset or delete that credential: a missing header gets `428`, a stale one `412`. Responses that change a credential return its new `ETag`. Generated passwords appear only in the response that creates them.

## Managing Platform Adapters

`/v1/platforms/adapters` lists every installed adapter, with its source, commit and who last changed it, and takes the same `ETag` and `If-Match` rules as credentials. A disabled adapter disappears from `/v1/platforms` and can't publish or link accounts, but still revokes tokens so users can unlink. Uninstalling is refused with `409` while accounts are linked through the adapter; disable it instead, or remove it with `./publisher.sh platforms remove --force`.

## Pagination

List endpoints return `{"data": [...], "next": ..., "prev": ...}`, newest first. Follow `next` and `prev` as they are: they keep your filters and `limit`, and are `null` on the last and first page. Don't build the `cursor` yourself.

`since` and `until` take ISO-8601 times, UTC if there's no offset. `since` is inclusive and `until` exclusive.

## Audit Events

`GET /v1/audit-events` needs `audit:read`, and each area also needs its read scope: `creds:read` for `auth.*` and `creds.*` events, `platforms:read` for `platforms.*`. Events from areas you can't read are left out.

| Action | Recorded when |
| :--- | :--- |
| `creds.create`, `creds.update`, `creds.reset_password`, `creds.revoke_sessions`, `creds.delete` | A credential changes, over the API or the CLI. `details` says what changed, never secrets. |
| `auth.login` | A web session starts, or a login for an existing username is refused |
| `auth.logout` | A web session ends |
| `platforms.add`, `platforms.update`, `platforms.remove` | An adapter is installed, updated or removed. `details` has the source URL and commits. |
| `platforms.enable`, `platforms.disable` | An adapter is offered to users again, or hidden from them |

`outcome` is `success`, `denied` (the change went beyond the actor's scopes) or `failed` (a refused login for an existing username: wrong password or disabled). Successful HTTP Basic requests aren't recorded, since every request authenticates. `actor` is the username at the time, and null for the CLI or a failed login. Events are kept for `AUDIT_RETENTION_DAYS` (365 by default).

## Publishing

`POST /v1/publications` takes JSON and tags payloads with protocol `https`. `POST /v1/twilio-sms` takes Twilio's webhook and tags them `sms`. See [Offline Publishing](../README.md#offline-publishing) for how the protocol and `tag` decide whether offline payloads publish.

Both only check the payload's structure before queueing it. Decryption, payload type and adapter errors happen later, so they're logged on the server, not returned.

## Errors

Error bodies are `{"error": "<message>"}`. The message is meant to be shown to users; the server logs more detail.

| Status | Meaning |
| :--- | :--- |
| `400 Bad Request` | Invalid parameters or payload, invalid cursor, or invalid time window |
| `401 Unauthorized` | Missing or invalid credentials |
| `403 Forbidden` | Origin not allowed, missing scope, or a credential change beyond your scopes |
| `404 Not Found` | Platform, key or credential not found |
| `409 Conflict` | Username taken, or the credential changed during the request; retry |
| `412 Precondition Failed` | `If-Match` doesn't match the current `ETag`; reload and retry |
| `422 Unprocessable Entity` | Validation error |
| `428 Precondition Required` | `If-Match` header missing |
| `429 Too Many Requests` | Rate limited (login and Basic auth) |
| `500 Internal Server Error` | Unexpected server error |
