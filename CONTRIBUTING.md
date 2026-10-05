# Contributing

## Setup

```bash
python3 -m venv venv && source venv/bin/activate
pip install -r requirements-dev.txt
pre-commit install
make build
```

`make test` runs the suite and `make check` runs every hook. CI runs both.

## Code conventions

The hooks enforce formatting, lint, types and commit messages. These rules are checked in review:

- **Functions by default.** Modules group related behaviour. Use a class only for real state (a cache, a connection) or when a framework needs one (ORM models, structs, interceptors, servicers, config sections).
- **Dependencies are arguments.** Domain and model functions take the database `session` first, then anything else they need, such as the adapter manager.
- **The entry point owns the transaction.** A route, gRPC handler, task or CLI command opens the session; code below it never opens a session or commits.
- **Domain errors subclass `PublisherError`** (`publisher/errors.py`). Each interface maps them to its own responses.
- **Loggers are `logging.getLogger(__name__)`.** Each entry point calls `publisher.log.setup_logging()` once.
- **Comments explain why, not what.** Docstrings are one line unless callers need a `Raises:` section.
