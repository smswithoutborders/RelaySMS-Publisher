# Troubleshooting

Start with the logs of the service involved:

```bash
sudo ./manage.sh logs --unit <SERVICE> --since "1 hour ago"
```

`<SERVICE>` is one of the [units `logs` takes](services.md#managesh).

## Services

### A service won't start

The service refuses to start on an invalid setting it uses. Run `sudo ./manage.sh check`, fix what it reports in `.env`, then `sudo ./manage.sh restart`.

### `update` ends with `.env has errors`

The new version needs a setting `.env` lacks. Run `sudo ./sync-env.sh`, fill in what `sudo ./manage.sh check` reports, then `sudo ./manage.sh restart`.

### `/health` returns `500`

The REST API can't open the database: the database server is down, its settings in `.env` are wrong, or, with SQLite, the service user can't read `data/`. See [Database](../installation/database.md).

### The email listener service is inactive

It exits at once while `SMTP_TRANSPORT_ENABLED` is off. See [SMTP transport](../configuration/smtp-transport.md).

### Docker refuses connections right after starting

The container applies migrations before the services start. Wait, or follow `docker compose logs -f`.

## Publishing

### A payload is accepted but never published

`POST /v1/publications` only queues a payload; the worker decides later. Follow `sudo ./manage.sh logs --unit worker` and match the line:

| Log line | Cause |
| --- | --- |
| `Published via '<PLATFORM>'.` | It worked |
| `Failed to process payload: ...` | The payload didn't decrypt or validate, or its keys are unknown or used up |
| `Rejected payload: ...` | Offline publishing refused it ([Offline publishing](../configuration/offline-publishing.md)) |
| `Failed to publish message: Adapter error: ...` | The platform refused it. The rest of the line is the adapter's reason. Fix it with the platform's [provider guide](../platforms/manage.md#provider-guides), then the user sends the message again. |
| `Sent via '<PLATFORM>', but couldn't record the result.` | It was published, but a database error kept it out of the stats. The traceback follows. |
| `Session <ID> can't be assembled from <N> segment(s): ...` | A multi-part payload's segments don't fit together |
| `An unexpected error occurred during task processing.` | A bug. The traceback follows. [Report it](https://github.com/smswithoutborders/RelaySMS-Publisher/issues). |
| No line at all | The worker isn't running (`sudo ./manage.sh status`), or a multi-part payload is still waiting for its other segments, for up to `PAYLOAD_SESSION_MAX_AGE_HOURS`, then it's discarded and recorded as `failed` with reason `segments_missing` |

`GET /v1/stats/publications` lists each failure and rejection with a reason code, for credentials with `stats:publications:reasons`.

### Linking an account fails

Check the adapter shows ✓ under Configured in `sudo ./publisher.sh platforms list`, then see its [provider guide](../platforms/manage.md#provider-guides)'s troubleshooting.

## Relay

### An SMS was sent, but the worker logs nothing

Check that the relay received it:

- With Deku SMS, the phone is online and Deku SMS is its default SMS app.
- With Twilio, follow the relay's log (`sudo journalctl -u relaysms-gatewayclient-twilio`) and Twilio's error log, under Monitor > Logs > Errors in the Twilio console.

### The Twilio relay answers `403` `Invalid Twilio signature.`

The webhook URL in the Twilio console doesn't match the URL the relay sees, scheme and host included. Set it to the relay's exact `https://` URL.

### The Twilio relay answers `502` `Forwarding failed.`

A `FORWARD_URLS_JSON` URL refused the payload or couldn't be reached. The relay's log names it. Check that `https://<HOST>/v1/publications` answers from the relay's host.

## REST API

### `Invalid username or password.`

The credential doesn't exist, the password is wrong, or it's disabled (`sudo ./publisher.sh creds list`).

### `Missing scope: ...`

Add the scope with `sudo ./publisher.sh creds set-scopes` ([Scopes](credentials.md#scopes)).

### `Session expired or invalid. Please log in again.`

The session idled past `AUTH_SESSION_IDLE_MINUTES`, reached `AUTH_SESSION_MAX_HOURS`, or was ended by `reset-password`, `disable` or `revoke-sessions`. Log in again.

### `Origin not allowed.`

The web client's origin is neither the API's own nor listed in `AUTH_WEB_ORIGINS`. Logins and writes with a session cookie both check it. Add the origin, which must be on the same site as the API, then `sudo ./manage.sh restart`.

### `Too many requests. Please try again shortly.`

nginx rate-limits logins and HTTP Basic requests ([limits](credentials.md#logging-in)). Wait a minute and try again.

## nginx

### gRPC calls fail through nginx

gRPC needs HTTP/2 on the HTTPS block. Run `sudo ./manage.sh nginx` to render the site again with it.

### `nginx -t` fails after an update

Run `sudo ./manage.sh nginx`: it renders the site from the current template, and restores the previous file if the new one fails.
