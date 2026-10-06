# Contributing

Thanks for helping improve RelaySMS Publisher. This guide covers how to report problems, set up a development environment, find your way around the code and get a pull request merged.

## Contents

- [Ways to contribute](#ways-to-contribute)
- [Reporting security issues](#reporting-security-issues)
- [Development setup](#development-setup)
- [Workflow](#workflow)
- [Project layout](#project-layout)
- [Code conventions](#code-conventions)
- [Testing](#testing)
- [Common changes](#common-changes)
- [Documentation](#documentation)
- [When CI fails](#when-ci-fails)
- [AI-assisted contributions](#ai-assisted-contributions)
- [License](#license)

## Ways to contribute

**Report a bug.** Search the [issues](https://github.com/smswithoutborders/RelaySMS-Publisher/issues) first. A useful report has:

- what you did, what you expected and what happened instead;
- the smallest steps or payload that reproduce it;
- the commit or release, Python version, database and how you run the services (systemd, Docker, `make run`);
- relevant log lines, with tokens, keys and phone numbers removed.

**Suggest a feature.** Open an issue that describes the problem before the solution. For anything that changes the payload format, the gRPC or REST contract, or the database schema, agree on the design in the issue before writing code.

**Fix something.** Small fixes (typos, clear bugs with a test) can go straight to a pull request. For larger changes, comment on the issue first so work isn't duplicated.

## Reporting security issues

> [!CAUTION]
> Don't open a public issue for a vulnerability. Email **<developers@smswithoutborders.com>** with a description, the affected versions and steps to reproduce. We'll confirm receipt and keep you updated until a fix is released.

## Development setup

### Prerequisites

- Python 3.12 or newer
- System packages (Ubuntu):

  ```bash
  sudo apt install python3-dev build-essential libsqlcipher-dev libmagic1 pkg-config make git
  ```

- Rust and cargo, to build the payload-specs library. Install them with [rustup](https://rustup.rs) if `cargo --version` fails:

  ```bash
  curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y
  source "$HOME/.cargo/env"
  ```

### Install

[Fork the repository](https://github.com/smswithoutborders/RelaySMS-Publisher/fork) on GitHub, then clone your fork and add this repository as `upstream`:

```bash
git clone --recurse-submodules git@github.com:<your-username>/RelaySMS-Publisher.git
cd RelaySMS-Publisher
git remote add upstream git@github.com:smswithoutborders/RelaySMS-Publisher.git
python3 -m venv venv && source venv/bin/activate
pip install -r requirements-dev.txt
pre-commit install --install-hooks
make build      # gRPC code and payload-specs bindings
```

> [!NOTE]
> `make build` generates files that are gitignored. Run it again after pulling changes to `protos/` or the `lib_relaysms_payload_specs` submodule.

### Run locally

```bash
cp template.env .env            # then edit as needed
python -m publisher config check
make migrate
make run                        # gRPC, REST, SMTP, worker and beat in the foreground
```

Each service can also run on its own:

| Service | Command |
| --- | --- |
| REST API | `uvicorn publisher.api.rest.app:app` |
| gRPC | `python -m publisher.api.grpc` |
| SMTP | `python -m publisher.smtp` |
| Celery worker and beat | `celery -A publisher.tasks.celery_app:celery_app worker` / `beat` |
| CLI | `python -m publisher --help` (or `./publisher.sh`) |

`python -m tools.client` drives the gRPC and REST flows by hand, see [tools/README.md](tools/README.md).

### Make targets

| Target | Does |
| --- | --- |
| `make build` | `protos` and `specs` |
| `make protos` | Generate the gRPC code from `protos/*/*.proto` |
| `make specs` | Build the pinned payload-specs commit and its Python bindings |
| `make migrate` | Apply Alembic migrations |
| `make run` | Start every service |
| `make test` | Run pytest |
| `make test-e2e` | Install, update and uninstall in a systemd container (podman) |
| `make check` | Run every pre-commit hook on all files |
| `make clean` | Remove generated code |

## Workflow

### Branches

- Branch from `staging` and open pull requests against `staging`.
- `staging` deploys to the staging server on every push.
- `staging` is merged into `main` for a release.

Name branches after the change, such as `fix/token-id-zero` or `feat/grpc-sync-keys`. Start each one from the latest upstream `staging`, push it to your fork and open the pull request from there:

```bash
git fetch upstream
git switch -c fix/token-id-zero upstream/staging
# ...commit...
git push -u origin fix/token-id-zero
```

If `staging` moves on while your PR is open, rebase onto it and force-push:

```bash
git fetch upstream
git rebase upstream/staging
git push --force-with-lease
```

> [!TIP]
> Leave "Allow edits by maintainers" ticked so small fixes can be pushed to your branch.

### Commits

Commit messages follow [Conventional Commits](https://www.conventionalcommits.org/), checked by commitizen in the `commit-msg` hook:

```
<type>(<optional scope>): <summary>

<optional body: why the change was needed>

<optional footer, e.g. BREAKING CHANGE: ...>
```

Common types are `feat`, `fix`, `refactor`, `test`, `docs`, `build`, `ci` and `chore`. Scopes name the area, such as `grpc`, `rest`, `auth`, `keys` or `manage`. Mark breaking changes with `!` (`feat(auth)!: ...`) and explain the migration path in a `BREAKING CHANGE:` footer. Breaking changes include removed or renamed env vars, CLI commands, endpoints, RPC fields and anything an operator must do by hand on update.

### Hooks

`pre-commit install` sets up three stages:

- **pre-commit:** whitespace and line-ending fixes, YAML/TOML checks, ruff lint and format, shellcheck and shfmt for shell scripts, hadolint and dockerfmt for Dockerfiles, dclint for Compose files, pyright and import-linter;
- **commit-msg:** commitizen;
- **pre-push:** the test suite.

> [!TIP]
> Hooks only see tracked files, so `git add` new files before running `make check`.

### Pull request checklist

- [ ] The PR targets `staging` and does one thing. Split unrelated changes.
- [ ] `make check` and `make test` pass locally.
- [ ] New behaviour and bug fixes come with tests. A bug fix has a test that fails without it.
- [ ] Docs, `template.env` and the README are updated if behaviour, settings or commands changed.
- [ ] Schema changes include a migration.
- [ ] The description says what changed, why, and how it was tested. Link the issue with `Closes #123`.
- [ ] Anything operators must do on deploy is called out.

A maintainer reviews every PR. Address comments with new commits; they're squashed or tidied on merge as needed.

## Project layout

| Path | Holds |
| --- | --- |
| `publisher/api/rest`, `api/grpc`, `smtp`, `cli` | Entry points: they parse input, open the session and call the domain code |
| `publisher/tasks` | Celery tasks, queued by the entry points and run by the worker |
| `publisher/keys.py`, `publications.py`, `tokens.py`, `credentials.py`, `platforms/`, `gateway_clients/` | Domain logic |
| `publisher/config.py`, `db/`, `models/`, `log.py`, `errors.py`, `crypto.py` | Infrastructure |
| `deploy/` | systemd units and nginx templates |
| `scripts/` | Install, setup and maintenance scripts used by `manage.sh` |
| `migrations/` | Alembic migrations |
| `protos/` | gRPC service definitions |
| `tools/` | The reference client |
| `data/` | Runtime data: installed adapters, registries (not tracked) |
| `tests/` | Tests, see [Testing](#testing) |

Each code row may import only the rows below it, never the other way round, and entry points don't import each other. import-linter enforces this in `make check`.

### How a publication flows

1. A payload arrives over REST (`/v1/publications`, the Twilio webhook) or SMTP.
2. The entry point validates it, queues `publish_message` and returns.
3. The worker runs `publisher/tasks/publication_task.py`, which calls `publications.publish`.
4. `publications` decrypts the payload with the token's per-slot keys (`keys.py`) and sends the content through the platform adapter (`platforms/`).
5. The task records the outcome in the publication stats.

The gRPC service handles the account side: storing OAuth2 and PNBA tokens, revoking them and syncing key pools.

## Code conventions

The hooks enforce formatting, lint, types and commit messages. These rules are checked in review:

- **Functions by default.** Modules group related behaviour. Use a class only for real state (a cache, a connection) or when a framework needs one (ORM models, structs, interceptors, servicers, config sections).
- **Dependencies are arguments.** Domain and model functions take the database `session` first, then anything else they need, such as the adapter manager.
- **The entry point owns the transaction.** A route, gRPC handler, task or CLI command opens the session; code below it never opens a session or commits.
- **Domain errors subclass `PublisherError`** (`publisher/errors.py`). Each interface maps them to its own responses: HTTP status codes, gRPC status codes, SMTP replies.
- **Loggers are `logging.getLogger(__name__)`.** Each entry point calls `publisher.log.setup_logging()` once. Never log tokens, keys, passwords or decrypted content.
- **Comments explain why, not what.** Docstrings are one line unless callers need a `Raises:` section.
- **Mark overridden framework methods with `@typing.override`.**
- **Code must run on Python 3.12.** Quote `TYPE_CHECKING` forward references (`Mapped["Token"]`) and avoid syntax newer than 3.12.
- **Every `.py` file starts with** `# SPDX-License-Identifier: GPL-3.0-only`.

Shell scripts follow one layout: `#!/usr/bin/env bash`, the SPDX line, `set -Eeuo pipefail`, then `source` `scripts/lib.sh` for logging, errors and shared helpers. Scripts with options parse them in `parse_args` and run from `main "$@"`. `install.sh` is the one exception: piped through curl, it clones the repo first and re-runs from the clone.

> [!WARNING]
> `platforms/protocol_interfaces.py` is excluded from every tool because adapters copy it verbatim. Keep changes to it backwards compatible.

## Testing

```bash
make test                                    # whole suite
python -m pytest tests/api/rest -q           # one directory
python -m pytest -k token_id -x              # by name, stop at first failure
```

Tests run against in-memory SQLite. `tests/conftest.py` sets the environment before `publisher.config` is imported, so your local `.env` is ignored.

| Directory | Covers | Runs in |
| --- | --- | --- |
| `tests/` (mirroring `publisher/`) | The Python package | `make test` |
| `tests/scripts` | The shell scripts, run with bash | `make test` |
| `tests/e2e` | Install, update and uninstall on Ubuntu 24.04 and Debian 13 | `make test-e2e` |

`make test-e2e` installs the working tree, uncommitted changes included, into systemd containers. It needs rootless podman and network access, and takes a few minutes; `PYTEST_ARGS="-k debian"` runs one distro. The staging deploy waits for it.

### Writing tests

- Put a test where its module lives: `publisher/api/rest/v1/stats.py` is tested in `tests/api/rest/test_stats.py`.
- Name tests after the behaviour, such as `test_get_rejects_ids_outside_0_255`, not the function.
- Test through the public interface (a route, an RPC, a domain function) and assert on outcomes: responses, rows, raised errors. Patch only what crosses the process boundary, such as adapter IPC or outbound HTTP.
- A bug fix needs a test that fails before the fix.

### Fixtures and helpers

| Name | Where | Gives |
| --- | --- | --- |
| `test_db` | `tests/fixtures.py` | A fresh in-memory database with every table |
| `fast_hasher` | `tests/fixtures.py` | A cheap password hasher, for credential tests |
| `app`, `client` | `tests/fixtures.py` | The FastAPI app and a `TestClient` for it |
| `password` | `tests/fixtures.py` | A valid credential password |
| `set_config` | `tests/conftest.py` | Changes a config section for one test |
| `USERNAME`, `create_credential`, `basic_auth`, `login`, `can_log_in` | `tests/helpers.py` | Credential and auth helpers |

Modules that touch the database opt in at the top:

```python
pytestmark = pytest.mark.usefixtures("test_db", "fast_hasher")
```

### Checking Python 3.12

CI runs the suite on 3.12, 3.13 and 3.14. To check 3.12 locally with [uv](https://docs.astral.sh/uv/):

```bash
uv venv --python 3.12 .venv312
uv pip install --python .venv312 -r requirements-dev.txt
make build test PYTHON=.venv312/bin/python
```

## Common changes

### Add a setting

1. Add the field to its section in `publisher/config.py` and read it in that section's `load`.
2. Add it, commented, to `template.env` and to the Configuration section of the README.
3. Check validation with `python -m publisher config check`, and add a test in `tests/test_config.py`.

### Change the database schema

1. Change the model in `publisher/models/`.
2. Add `migrations/versions/NNN_short_slug.py` with the next number as `revision` and the previous one as `down_revision` (`"014"` after `"013"`). Write both `upgrade` and `downgrade`.
3. Run `make migrate` on SQLite, and on MySQL or PostgreSQL if the migration uses dialect-specific features.

### Add a REST endpoint

1. Add the route to the matching module in `publisher/api/rest/v1/` (or a new module with its own `APIRouter`, registered in `routes.py`).
2. Put request and response models in `schemas.py`. Use `Depends(get_db)` for the session and map domain errors to `HTTPException`.
3. Test it in `tests/api/rest/`, describe it in its docstring and run `make docs`. Update [docs/rest.md](docs/rest.md) only for what the reference doesn't show.

### Change the gRPC API

1. Edit `protos/v3/publisher.proto` and run `make protos`.
2. Add a module per RPC in `publisher/api/grpc/v3/` and a thin method on the servicer that calls it.
3. Raise `grpc_interceptor` exceptions such as `InvalidArgument` or `Unauthenticated`; `ErrorInterceptor` turns them into status codes and anything else into `INTERNAL`.
4. Test it in `tests/api/grpc/` and update [docs/grpc.md](docs/grpc.md).

> [!WARNING]
> Deployed clients depend on the proto. Only add fields; never renumber, reuse or change the type of an existing field.

### Add a CLI command

Add a `click` command to the matching group in `publisher/cli/`, or a new module registered in `publisher/cli/__init__.py`. Open the session in the command and pass it down.

### Add a Celery task

Add it under `publisher/tasks/`. Keep the explicit `tasks.*` name so queued messages survive refactors, and add periodic tasks to the beat schedule in `celery_app.py`.

### Platform adapters

Adapters live outside this repository and are installed with `python -m publisher platforms`. See [platforms/README.md](platforms/README.md).

## Documentation

- [docs/rest.md](docs/rest.md) (with the generated [docs/openapi.json](docs/openapi.json)), [docs/grpc.md](docs/grpc.md) and [docs/smtp.md](docs/smtp.md) describe each interface. Update them in the same PR as the behaviour.
- The README covers installation, configuration and operations. Keep it in step with `template.env` and the CLI.
- Write plainly and briefly. Use code blocks for commands and tables for options.

## When CI fails

`.github/workflows/checks.yml` runs the hooks on Python 3.14 and the tests on 3.12, 3.13 and 3.14.

- **Hook failures:** run `make check` locally. Ruff and the whitespace hooks fix files in place, so re-add and commit the changes.
- **Pyright:** fix the type, or narrow it with an `assert`. Use `# pyright: ignore[rule]` only with a reason.
- **import-linter:** a lower layer imports a higher one. Move the code down a layer or pass the dependency in as an argument.
- **Tests pass on newer Pythons but fail on 3.12:** look for newer syntax or an unquoted forward reference.
- **Requirements check:** the pinned dependencies conflict. Run `pip install --dry-run -r requirements.txt -r requirements-observability.txt` to see the conflict.

## AI-assisted contributions

You may use AI tools, but you're responsible for every line you submit. You must understand each change well enough to explain it in review. Don't submit generated code you haven't read and tested, and don't paste AI output as answers to review comments.

## License

By contributing, you agree that your contributions are licensed under the [GNU General Public License v3.0](LICENSE.md).
