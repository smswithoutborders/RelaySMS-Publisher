# Contributing

This guide covers changing the Publisher's code, tests and manual. To install or run the Publisher, read the [manual](docs/README.md) instead.

## Contents

- [Where to start](#where-to-start)
- [Your first pull request](#your-first-pull-request)
- [Development setup](#development-setup)
- [Run the checks CI runs](#run-the-checks-ci-runs)
- [Testing](#testing)
- [Project layout](#project-layout)
- [Code conventions](#code-conventions)
- [Common changes](#common-changes)
- [Documentation](#documentation)
- [Commits and pull requests](#commits-and-pull-requests)
- [AI-assisted contributions](#ai-assisted-contributions)
- [License](#license)

## Where to start

| You want to | Do this |
| --- | --- |
| Report a vulnerability | Don't open an issue. Follow [SECURITY.md](SECURITY.md). |
| Report a bug | Search the [issues](https://github.com/smswithoutborders/RelaySMS-Publisher/issues), then open one with the details below. |
| Suggest a feature | Open an issue that describes the problem before the solution. |
| Change the payload format, the gRPC or REST contract, or the database schema | Agree on the design in an issue before writing code. |
| Fix a typo or a clear bug | Open a pull request with a test. Comment on the issue first for anything larger. |
| Change a platform adapter | Open it in the adapter's own repository. See [Platform adapters](#platform-adapters). |
| Change the payload-specs library | Open it in [rusty_relaysms_payload_specs](https://github.com/smswithoutborders/rusty_relaysms_payload_specs). This repository only pins a commit of it. |

A useful bug report has:

- what you did, what you expected and what happened instead
- the smallest steps or payload that reproduce it
- the commit or release, Python version, database and how you run the services (systemd, Docker or `make run`)
- relevant log lines, with tokens, keys and phone numbers removed

## Your first pull request

1. Install the [prerequisites](#prerequisites), then fork, clone and set up as in [Install](#install).
2. Branch from the latest upstream `staging`:

   ```bash
   git fetch upstream
   git switch -c fix/<SHORT_NAME> upstream/staging
   ```

3. Make the change, with a test that fails without it.
4. Run what CI runs:

   ```bash
   git add <NEW_FILES>   # hooks only see tracked files
   make check test
   ```

5. Commit with a [Conventional Commits](#commits) message, push to your fork and open a pull request against `staging`.

## Development setup

### Prerequisites

- Python 3.12 or newer
- System packages (Ubuntu or Debian):

  ```bash
  sudo apt install python3-dev python3-venv build-essential pkg-config \
      libsqlcipher-dev libmagic1 openssl make git curl
  ```

- Rust and cargo, to build the payload-specs library. Install them with [rustup](https://rustup.rs) if `cargo --version` fails:

  ```bash
  curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y
  source "$HOME/.cargo/env"
  ```

- [Podman](https://podman.io), rootless, only for `make test-dialects` and `make test-e2e`

### Install

[Fork the repository](https://github.com/smswithoutborders/RelaySMS-Publisher/fork), then:

```bash
git clone --recurse-submodules git@github.com:<GITHUB_USERNAME>/RelaySMS-Publisher.git
cd RelaySMS-Publisher
git remote add upstream git@github.com:smswithoutborders/RelaySMS-Publisher.git
make setup
```

`make setup` creates `venv` with the dev dependencies, installs the Git hooks, runs `make build`, creates `.env` with fresh encryption keys, checks the config and migrates the database. Running it again keeps an existing `.env`. `./sync-env.sh` adds the variables `.env` is missing from `template.env`.

Make targets use `venv/bin/python`. Run `source venv/bin/activate` before the `python` commands below.

> [!NOTE]
> `make build` generates gitignored files. Run it again after pulling changes to `protos/` or the `lib_relaysms_payload_specs` submodule.

### Run locally

```bash
make creds    # administrator "dev", prints the password once
make run      # every service in the foreground
```

`make run` starts gRPC, REST, the Celery worker and beat, and the SMTP listener when `SMTP_TRANSPORT_ENABLED=true`. Check your login against the REST API on the default `PORT`:

```bash
curl -u dev:<PASSWORD> http://127.0.0.1:16000/v1/auth/me
```

| To | Run |
| --- | --- |
| Run the REST API alone | `uvicorn publisher.api.rest.app:app` |
| Run gRPC alone | `python -m publisher.api.grpc` |
| Run SMTP alone | `python -m publisher.smtp` |
| Run the Celery worker or beat alone | `celery -A publisher.tasks.celery_app:celery_app worker` (or `beat`) |
| Use the CLI | `python -m publisher --help` |
| Fill the database with sample data | `python -m publisher seed --help` |
| Drive the gRPC and REST flows by hand | `python -m tools.client`, see [the reference client](docs/developers/reference-client.md) |

### Make targets

| Target | Does |
| --- | --- |
| `make setup` | Set up a development checkout, see [Install](#install) |
| `make build` | `protos` and `specs` |
| `make protos` | Generate the gRPC code from `protos/*/*.proto` |
| `make specs` | Build the pinned payload-specs commit and its Python bindings |
| `make migrate` | Apply Alembic migrations |
| `make creds` | Create an administrator credential, `dev` unless `CREDS_USER` is set |
| `make run` | Start every service |
| `make check` | Run every pre-commit hook on all files |
| `make test` | Run pytest |
| `make coverage` | Run pytest, list untested lines, and fail under the `fail_under` in `pyproject.toml` |
| `make test-sdk` | Test the adapter SDK in `sdk/` |
| `make test-dialects` | Migrate and query every supported database (podman) |
| `make test-e2e` | Install, update and uninstall in systemd containers (podman) |
| `make docs` | Regenerate `docs/openapi.json` from the REST app |
| `make book` | Build the manual in `docs/` into `book/` |
| `make book-serve` | Preview the manual on <http://localhost:3000>, rebuilding on changes |
| `make clean` | Remove generated code |

Every pytest target passes `PYTEST_ARGS` on, such as `make test PYTEST_ARGS="-k token -x"`.

## Run the checks CI runs

`make setup` installs three Git hooks: the pre-commit checks on `git commit`, commitizen on the commit message, and the test suite on `git push`.

| CI check | Runs on | Run it locally |
| --- | --- | --- |
| **Hooks** (formatting, ruff, pyright, import-linter, shell, Docker and YAML checks) | Every PR | `make check` |
| **Tests** on Python 3.12 and 3.13 | Every PR | `make test` |
| **Coverage** on Python 3.14 | Every PR | `make coverage` |
| **SDK** on Python 3.12 to 3.14 | Every PR | `make test-sdk` |
| **SDK version** | Every PR | Bump `version` in `sdk/pyproject.toml` when `sdk/src` changes |
| **Database dialects** | PRs touching the database code, migrations or requirements | `make test-dialects` |
| **E2E** (Ubuntu and Debian) | PRs touching the scripts, `deploy/`, migrations or requirements | `make test-e2e` |
| **Docs** (link check and book build) | PRs touching Markdown or the book | `make book` |
| **Check Requirements** | PRs touching `requirements*.txt` | `pip install --dry-run -r requirements-observability.txt` |

The workflows in [.github/workflows](.github/workflows) list the exact paths. **Database dialects** and **E2E** can also run from the Actions tab with **Run workflow**. A push to `staging` deploys once the checks that run on every PR pass.

Each pytest job adds a results table to the run's summary page, with the failing tests under it.

| When this fails | Try |
| --- | --- |
| Ruff or a whitespace hook | It fixed the files in place. Re-add them and commit. |
| Pyright | Fix the type, or narrow it with an `assert`. Use `# pyright: ignore[<RULE>]` only with a reason. |
| import-linter | A lower layer imports a higher one, see [Project layout](#project-layout). Move the code down a layer or pass the dependency in as an argument. |
| Tests pass on newer Pythons but fail on 3.12 | Look for newer syntax or an unquoted forward reference. See [Checking Python 3.12](#checking-python-312). |
| Coverage | Test the lines the report lists. |
| A dialect | `make test-dialects PYTEST_ARGS="-k mysql"` |
| A distro in E2E | `make test-e2e PYTEST_ARGS="-k debian"` |
| Check Requirements | The pinned dependencies conflict. The dry run above shows which. |

## Testing

```bash
make test                                    # whole suite
python -m pytest tests/api/rest -q           # one directory
python -m pytest -k token_id -x              # by name, stop at the first failure
```

Tests run against in-memory SQLite. `tests/conftest.py` sets the environment before `publisher.config` is imported, so your local `.env` is ignored.

| Directory | Covers | Run with |
| --- | --- | --- |
| `tests/` (mirroring `publisher/`) | The Python package | `make test` |
| `tests/scripts` | The shell scripts | `make test` |
| `tests/dialects` | Migrations and queries on SQLite, SQLCipher, Postgres, MySQL and MariaDB | `make test-dialects` |
| `tests/e2e` | Install, update and uninstall on Ubuntu 24.04 and Debian 13 | `make test-e2e` |

`make test-dialects` starts the database servers in rootless podman and removes them afterwards. It skips MariaDB on a host with an AppArmor profile for `mariadbd`, which stops the server in the container. Add a dialect test when a query or migration could behave differently on another database.

`make test-e2e` installs the working tree, uncommitted changes included, into systemd containers. It needs network access and takes a few minutes.

### Writing tests

- Put a test where its module lives: `publisher/api/rest/v1/stats.py` is tested in `tests/api/rest/test_stats.py`.
- Name tests after the behavior, such as `test_list_skips_disabled_items`, not the function.
- Test through the public interface (a route, an RPC, a domain function). Patch only what crosses the process boundary, such as adapter IPC or outbound HTTP.
- A module that touches the database opts in at the top:

  ```python
  pytestmark = pytest.mark.usefixtures("test_db", "fast_hasher")
  ```

Shared fixtures live in `tests/fixtures.py` and `tests/conftest.py`, and helpers in `tests/helpers.py`. The ones most tests use:

| Name | Gives |
| --- | --- |
| `test_db` | A fresh in-memory database with every table |
| `fast_hasher` | A cheap password hasher, for credential tests |
| `client`, `admin` | A `TestClient` for the REST app, and Basic auth headers for the administrator |
| `set_config` | Changes a config section bound in a module, for one test |
| `adapter_calls` | Fakes adapter processes: set `results[method]` to a result or an error, read `calls` back |

A test module can set `SUMMARY_BY` to group its rows in the CI summary by test or by a parametrized fixture, see `tests/summary.py`.

### Checking Python 3.12

To check 3.12 locally with [uv](https://docs.astral.sh/uv/):

```bash
uv venv --python 3.12 .venv312
uv pip install --python .venv312 -r requirements-dev.txt
make build test PYTHON=.venv312/bin/python
```

## Project layout

| Path | Holds |
| --- | --- |
| `publisher/api/rest`, `api/grpc`, `smtp`, `cli` | Entry points: they parse input, open the session and call the domain code |
| `publisher/tasks` | Celery tasks, queued by the entry points and run by the worker |
| `publisher/keys.py`, `publications.py`, `tokens.py`, `credentials.py`, `platforms/`, `gateway_clients/` | Domain logic |
| `publisher/config.py`, `db/`, `models/`, `log.py`, `errors.py`, `crypto.py` | Infrastructure |
| `sdk/` | The adapter SDK, released on its own |
| `migrations/` | Alembic migrations |
| `protos/` | gRPC service definitions |
| `deploy/` | systemd units and nginx templates |
| `scripts/` | Install, setup and maintenance scripts used by `manage.sh` |
| `tools/` | The reference client |
| `data/` | Runtime data, not tracked |

Each `publisher` row may import only the rows below it, and entry points don't import each other. import-linter enforces this in `make check`. The [architecture](docs/explanation/architecture.md) page shows how the services fit together.

### How a publication flows

1. A payload arrives over REST (`/v1/publications`) or SMTP.
2. The entry point validates it and calls `queue_publication`, which replaces the sender's address with a keyed hash and queues `publish_message`.
3. The worker runs `publisher/tasks/publication_task.py`. In one transaction, `publications.prepare` joins the payload's segments, deletes its keys and decrypts it. The transaction commits before anything is sent, so the payload can't publish twice.
4. With no transaction open, `publications.send` runs the adapter through `platforms/ipc.py`.
5. A new transaction stores any refreshed token (`finish` after a success) and records the outcome in the publication stats.

The gRPC service handles the account side: storing OAuth2 and PNBA tokens, revoking them and syncing key pools.

## Code conventions

The hooks enforce formatting, lint, types and commit messages. Review checks these:

- **Functions by default.** Modules group related behavior. Use a class only for real state (a cache, a connection) or when a framework needs one (ORM models, interceptors, servicers, config sections).
- **Dependencies are arguments.** Domain and model functions take the database `session` first, then anything else they need, such as the acting credential.
- **The entry point owns the transaction.** A route, gRPC handler, task or CLI command opens the session. Code below it never opens a session or commits.
- **No transaction stays open while an adapter runs,** since a call can take a minute.
- **Domain errors subclass `PublisherError`** (`publisher/errors.py`). Each interface maps them to its own responses: HTTP status codes, gRPC status codes, SMTP replies.
- **Loggers are `logging.getLogger(__name__)`.** Each entry point calls `publisher.log.setup_logging()` once. Never log tokens, keys, passwords or decrypted content.
- **Comments explain why, not what.** Docstrings are one line unless callers need a `Raises:` section. REST route docstrings become the API reference, so describe what a client needs there.
- **Mark overridden framework methods with `@typing.override`.**
- **Code must run on Python 3.12.** Quote `TYPE_CHECKING` forward references (`Mapped["Token"]`) and avoid syntax newer than 3.12.
- **Every `.py` file starts with** `# SPDX-License-Identifier: GPL-3.0-only`.

Shell scripts follow one layout: `#!/usr/bin/env bash`, the SPDX line, `set -Eeuo pipefail`, then `source` `scripts/lib.sh` for logging, errors and shared helpers. Scripts with options parse them in `parse_args` and run from `main "$@"`. `install.sh` is the one exception: piped through curl, it clones the repository first and re-runs from the clone.

## Common changes

### Add a setting

1. Add the field to its section in `publisher/config.py` and read it in that section's `load`.
2. Add it, commented, to `template.env` and to [the settings reference](docs/configuration/settings.md). A test fails until both list it.
3. Check validation with `python -m publisher config check`, and add a test in `tests/test_config.py`.

### Change the database schema

1. Change the model in `publisher/models/`. Import a new model in `publisher/models/__init__.py`, or tests won't create its table.
2. Add `migrations/versions/NNN_short_slug.py` with the next number as `revision` and the previous one as `down_revision`. Write both `upgrade` and `downgrade`.
3. Run `make migrate`, `python -m alembic downgrade -1` and `make migrate` again. Run `make test-dialects` if the migration uses dialect-specific features.
4. Put `[migrate]` in the commit message so the staging deploy applies it.

### Add a REST endpoint

1. Add the route to the matching module in `publisher/api/rest/v1/`, or a new module with its own `APIRouter` registered in `routes.py`.
2. Put request and response models in `schemas.py`. Use `Depends(get_db)` for the session, and `Security(authorize, scopes=[...])` if it needs a login. A new scope goes in `Scope` in `publisher/models/credential.py`.
3. Map domain errors to `ApiError` (`v1/errors.py`) with a message a client can show, and put ids and other detail in its `log=`.
4. Test it in `tests/api/rest/`, describe it in its docstring and run `make docs`. Update [the REST reference](docs/reference/rest-api.md) only for what the generated reference doesn't show.

### Change the gRPC API

> [!WARNING]
> Deployed clients depend on the proto: only add fields.

1. Edit `protos/v3/publisher.proto` and run `make protos`.
2. Add a module per RPC in `publisher/api/grpc/v3/` and a thin method on the servicer that calls it.
3. Raise `grpc_interceptor` exceptions such as `InvalidArgument` or `Unauthenticated`. `ErrorInterceptor` turns them into status codes and anything else into `INTERNAL`.
4. Test it in `tests/api/grpc/` and update [the gRPC reference](docs/reference/grpc-api.md).

### Add a CLI command

Add a `click` command to the matching group in `publisher/cli/`, or a new module registered in `publisher/cli/__init__.py`. Open the session in the command and pass it down.

### Add a Celery task

Add it under `publisher/tasks/`. Keep the explicit `tasks.*` name so queued messages survive refactors, and add periodic tasks to the beat schedule in `celery_app.py`.

### Platform adapters

Adapters live in their own repositories and are built with the SDK in `sdk/`, see [sdk/README.md](sdk/README.md) and [Writing an adapter](docs/developers/writing-an-adapter.md). Install one locally with `python -m publisher platforms add <GITHUB_URL>`.

A change to `sdk/src` needs a new `version` in `sdk/pyproject.toml`. Adapters pin SDK releases and run `.github/workflows/adapter.yml` at the tag they pin, so a change reaches an adapter only when it moves its pin.

## Documentation

The manual in `docs/` is an [mdBook](https://rust-lang.github.io/mdBook/) that reads the same on GitHub. Preview it with `make book-serve`.

- Update the pages a change affects in the same PR.
- List a new page in `docs/SUMMARY.md`, or the book leaves it out.
- Link pages in `docs/` relatively, and files outside it by their full GitHub URL, since the book only has `docs/`.
- Draw diagrams as `mermaid` code blocks.
- Say "web client" and "public", and use `publisher.example.com`, `example.com` and `+237600000000` in examples. Keep GitHub alerts for what readers must not miss.
- Start a task page with its requirements. End a page that points onward with a `## Next steps` section of one or two linked sentences or a short list. Skip it when the book's next page is the only next step.
- Use tables for reference data, numbered steps for procedures, and one heading per symptom for troubleshooting.
- Write plainly and briefly in US English, one paragraph per line, with sentence-case headings and `<UPPER_SNAKE>` placeholders.

## Commits and pull requests

### Branches

| Branch | Role |
| --- | --- |
| `staging` | Target of every pull request. Each push deploys to the staging server once the checks pass. |
| `main` | Releases. `staging` is merged into it. |
| Your branch | Named after the change, such as `fix/help-text-typo` or `feat/export-csv`, on your fork. |

If `staging` moves on while your PR is open, rebase onto it:

```bash
git fetch upstream
git rebase upstream/staging
git push --force-with-lease
```

### Commits

Messages follow [Conventional Commits](https://www.conventionalcommits.org/), checked by commitizen:

```
<type>(<optional scope>): <summary>

<optional body: why the change was needed>

<optional footer, e.g. BREAKING CHANGE: ...>
```

Keep it to the summary line unless the change needs explaining:

```
fix(cli): show the missing file when a command fails
feat(reports)!: rename REPORTS_DIR to REPORTS_PATH
```

- Types are commitizen's, such as `feat`, `fix`, `refactor`, `test` and `docs`. Scopes name the area, such as `grpc`, `rest` or `auth`.
- Mark breaking changes with `!` and explain the migration path in a `BREAKING CHANGE:` footer. Breaking changes include removed or renamed env vars, CLI commands, endpoints and RPC fields, and anything an operator must do by hand on update.
- Add `[migrate]` to a commit that adds a migration, such as `feat(reports): add a reports table [migrate]`.

### Pull request checklist

- [ ] The PR targets `staging` and does one thing. Unrelated cleanups go in their own PR.
- [ ] `make check` and `make test` pass locally, plus the [path-triggered checks](#run-the-checks-ci-runs) your change touches.
- [ ] New behavior comes with tests. A bug fix has a test that fails without it.
- [ ] The manual in `docs/` and `template.env` are updated if behavior, settings or commands changed.
- [ ] Schema changes include a migration and a commit message with `[migrate]`.
- [ ] The description says what changed, why, and how it was tested, and links the issue with `Closes #<ISSUE>`.
- [ ] Anything operators must do on deploy is called out.

### Review

A maintainer reviews every PR. Leave "Allow edits by maintainers" ticked. Answer each comment, push fixes as new commits rather than rewriting the branch, and re-request review when you're done. Commits are squashed or tidied on merge as needed.

## AI-assisted contributions

You may use AI tools, but you're responsible for every line you submit. You must understand each change well enough to explain it in review. Don't submit generated code you haven't read and tested, and don't paste AI output as answers to review comments.

## License

By contributing, you agree that your contributions are licensed under the [GNU General Public License v3.0](LICENSE.md).
