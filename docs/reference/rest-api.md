# REST API

The REST API serves platform, gateway client and server key metadata, accepts encrypted payloads for publishing, and lets credentials read stats, manage credentials and read the audit log.

The endpoint reference is [openapi.json](../openapi.json), generated from the app. Open it in any OpenAPI viewer, or set `API_DOCS_ENABLED=true` on a development server and browse `/docs`.

This page covers what the reference doesn't show well.

## Base URL

```
https://<host>/v1
```

`/health` is the only endpoint outside `/v1`.

## Authentication

Admin endpoints take a web session cookie or HTTP Basic credentials; see [Logging in](../operating/credentials.md#logging-in). Each endpoint's description names the scopes it needs.

## Managing credentials

A credential can only grant scopes it holds, can't change itself, and can't change a credential holding scopes it lacks. These return `403`.

`GET /v1/creds/{username}` returns an opaque `ETag`. Send it back unchanged as `If-Match` to change, reset or delete that credential: a missing header gets `428`, a stale one `412`. Responses that change a credential return its new `ETag`. Generated passwords appear only in the response that creates them.

## Managing platform adapters

`/v1/platforms/adapters` lists every installed adapter, with its source, version tag, commit and who last changed it, and takes the same `ETag` and `If-Match` rules as credentials. A disabled adapter disappears from `/v1/platforms` and can't publish or link accounts, but still revokes tokens so users can unlink. Uninstalling is refused with `409` while accounts are linked through the adapter; see [Removing](../platforms/manage.md#removing).

Installing (`POST /v1/platforms/adapters`) and updating (`POST /v1/platforms/adapters/{id}/update`) run code from the repository on the server, so they need an administrator and a repository from an org in `PLATFORMS_GITHUB_ORGS`. Both take an optional `tag`, defaulting to the newest version tag, and return `202` with the job's URL in `Location`. Poll the job until its `state` is `succeeded` or `failed`; its `log` has the end of the git and pip output. An adapter has one job at a time; another gets `409`.

An adapter's settings are at `/v1/platforms/adapters/{id}/config`, for administrators only. `GET` lists each setting, with secrets only marked `is_set`, and the inputs its setup takes. `PATCH` changes the settings sent and keeps the rest; `POST .../setup` runs the adapter's setup and replaces them all, with a file input sent as the file's text. `configured` in the adapter list says whether every required setting has a value.

## Managing gateway clients

`/v1/gateway-clients/registry` lists every gateway client, with who last changed it, and takes the same `ETag` and `If-Match` rules as credentials (scopes `gc:read` and `gc:write`). `GET /v1/gateway-clients/registry/suggest?msisdn=` returns the details and PLMN candidates a create would use, to prefill a form for the administrator to confirm; see [how suggest works](../gateway-clients/manage.md#how-suggest-works). A disabled client disappears from the public `/v1/gateway-clients`.

## Pagination

List endpoints return `{"data": [...], "next": ..., "prev": ...}`, newest first. Follow `next` and `prev` as they are: they keep your filters and `limit`, and are `null` on the last and first page. Don't build the `cursor` yourself.

`since` and `until` take ISO-8601 times, UTC if there's no offset. `since` is inclusive and `until` exclusive.

## Audit events

`GET /v1/audit-events` returns the [audit log](../operating/audit-log.md).

## Publishing

`POST /v1/publications` takes JSON and tags payloads with protocol `https`. It needs no credentials: a payload publishes only if it decrypts with the keys of a linked account or, for an offline payload, passes the [offline publishing](../configuration/offline-publishing.md) rules. See [offline publishing](../configuration/offline-publishing.md) for how the protocol and `tag` decide whether offline payloads publish.

It only checks the payload's structure before queueing it. Decryption, payload type and adapter errors happen later, so they're logged on the server, not returned.

## Errors

Error bodies are `{"error": "<message>"}`. The message is meant to be shown to users; the server logs more detail.

| Status | Meaning |
| :--- | :--- |
| `400 Bad Request` | Invalid parameters or payload, invalid cursor, or invalid time window |
| `401 Unauthorized` | Missing or invalid credentials |
| `403 Forbidden` | Origin not allowed, missing scope, or a credential change beyond your scopes |
| `404 Not Found` | The resource doesn't exist |
| `409 Conflict` | Already exists, in use, or changed by another request at the same moment; retry |
| `412 Precondition Failed` | `If-Match` doesn't match the current `ETag`; reload and retry |
| `422 Unprocessable Entity` | Validation error |
| `428 Precondition Required` | `If-Match` header missing |
| `429 Too Many Requests` | Rate limited (login and Basic auth) |
| `500 Internal Server Error` | Unexpected server error |
