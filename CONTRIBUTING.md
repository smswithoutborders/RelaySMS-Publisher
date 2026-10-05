# Contributing

## Setup

```bash
python3 -m venv venv && source venv/bin/activate
pip install -r requirements-dev.txt
pre-commit install
make build
```

`make test` runs the suite and `make check` runs every hook. CI runs both.

## Layout

| Path | Holds |
| --- | --- |
| `publisher/api/rest`, `api/grpc`, `smtp`, `cli` | Entry points: they parse input, open the session and call the domain code |
| `publisher/tasks` | Celery tasks, queued by the entry points and run by the worker |
| `publisher/keys.py`, `publications.py`, `tokens.py`, `credentials.py`, `platforms/`, `gateway_clients/` | Domain logic |
| `publisher/config.py`, `db/`, `models/`, `log.py`, `errors.py`, `crypto.py` | Infrastructure |
| `deploy/`, `scripts/`, `migrations/`, `protos/`, `tools/` | systemd and nginx templates, install and ops scripts, Alembic, gRPC protos, the reference client |

Each code row may import only the rows below it, never the other way round, and entry points don't import each other. import-linter checks this in `make check`. Tests mirror the package under `tests/`.

## Code conventions

The hooks enforce formatting, lint, types and commit messages. These rules are checked in review:

- **Functions by default.** Modules group related behaviour. Use a class only for real state (a cache, a connection) or when a framework needs one (ORM models, structs, interceptors, servicers, config sections).
- **Dependencies are arguments.** Domain and model functions take the database `session` first, then anything else they need, such as the adapter manager.
- **The entry point owns the transaction.** A route, gRPC handler, task or CLI command opens the session; code below it never opens a session or commits.
- **Domain errors subclass `PublisherError`** (`publisher/errors.py`). Each interface maps them to its own responses.
- **Loggers are `logging.getLogger(__name__)`.** Each entry point calls `publisher.log.setup_logging()` once.
- **Comments explain why, not what.** Docstrings are one line unless callers need a `Raises:` section.
