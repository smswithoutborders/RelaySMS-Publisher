# RelaySMS Adapter SDK

Build platform adapters for the [RelaySMS Publisher](https://github.com/smswithoutborders/RelaySMS-Publisher). The Publisher runs each adapter in its own virtual environment and talks to it over JSON-RPC 2.0 on standard input and output.

[`examples/echo-adapter`](examples/echo-adapter) is a complete adapter to start from.

## Layout

Name the repository, the distribution and the package after the platform and protocol, such as `gmail-oauth2-adapter` and `gmail_oauth2_adapter`.

```
adapter.toml                    describes the adapter to the Publisher
pyproject.toml
README.md
src/gmail_oauth2_adapter/
  __init__.py                   exports the adapter class
  adapter.py
tests/
```

In `pyproject.toml`:

```toml
dependencies = [
  "relaysms-adapter-sdk @ git+https://github.com/smswithoutborders/RelaySMS-Publisher@sdk-v1.0.0#subdirectory=sdk",
]

[project.optional-dependencies]
dev = [
  "pytest",
  "relaysms-adapter-sdk[console] @ git+https://github.com/smswithoutborders/RelaySMS-Publisher@sdk-v1.0.0#subdirectory=sdk",
]

[tool.hatch.metadata]
allow-direct-references = true
```

## Write an adapter

Subclass `OAuth2Adapter` or `PNBAAdapter` and implement its methods. Any of them may be `async`.

| Class | Method | Takes | Returns |
|---|---|---|---|
| both | `send_message` | `SendRequest` | `SendResult` (with `token` when it was refreshed) |
| both | `revoke` | `RevokeRequest` | `None` |
| `OAuth2Adapter` | `create_authorization_url` | `AuthorizationRequest` | `AuthorizationUrl` |
| `OAuth2Adapter` | `exchange_code` | `CodeExchangeRequest` | `Account` |
| `PNBAAdapter` | `send_code` | `CodeRequest` | `CodeSent` |
| `PNBAAdapter` | `verify_code` | `CodeVerificationRequest` | `Account` or `PasswordRequired` |
| `PNBAAdapter` | `verify_password` (optional) | `PasswordVerificationRequest` | `Account` |

`Account.token` is stored by the Publisher and passed back on every `send_message` and `revoke`, so keep its shape stable across releases.

If `send_message` refreshed the token and then fails, put the new token in the error's `data["token"]` so the Publisher still stores it. This matters for platforms whose refresh tokens are single use.

### Errors

Raise these so the Publisher can act on the failure. Any other exception is logged and reported as an internal error, without its details.

| Error | When |
|---|---|
| `InvalidParamsError` | The request is missing something the adapter needs |
| `AuthenticationError` | The user's code, password or authorization was rejected |
| `TokenInvalidError` | The stored token no longer works; the user must link again |
| `RateLimitedError` | The platform is throttling, optionally with `retry_after` seconds |
| `UpstreamError` | The platform failed or couldn't be reached |

### Files

The Publisher replaces the adapter's code on every update, so never write next to it.

| Function | Holds |
|---|---|
| `config_dir()` | Credentials and settings, such as `credentials.json` |
| `state_dir()` | Anything the adapter writes, such as databases |

Log with `logging.getLogger(__name__)`. Records go to standard error at `LOG_LEVEL` (`INFO` by default), and the Publisher logs them at the same level.

## Describe it

Put `adapter.toml` at the repository root:

```toml
entry = "gmail_oauth2_adapter:GmailAdapter"
name = "gmail"
display_name = "Gmail"
protocol = "oauth2"        # oauth2 or pnba
category = "email"         # email, message, text or bridge
offline_first = false
auth_provider = "self"     # optional

[icons]
svg = "https://raw.githubusercontent.com/.../icon.svg"
png = "https://raw.githubusercontent.com/.../icon.png"
```

## Try it

`relaysms-adapter` runs the adapter in the current directory the way the Publisher does, keeping its config, state and the linked account in `.relaysms/`. Add `.relaysms/` to `.gitignore`.

```bash
python3 -m venv venv
venv/bin/pip install -e '.[dev]'
mkdir -p .relaysms/config && cp ~/Downloads/credentials.json .relaysms/config/
venv/bin/relaysms-adapter link
venv/bin/relaysms-adapter send
venv/bin/relaysms-adapter revoke
```

| Command | Does |
|---|---|
| `link` | OAuth2: opens the authorization URL and catches the redirect on a local `http://localhost` redirect URL, or asks you to paste it. PNBA: asks for the phone number, code and two-step password. |
| `send` | Sends from the linked account, asking for what the category needs. `--to`, `--subject`, `--body` and `--attach` skip the questions; `--offline` sends without an account. |
| `revoke` | Unlinks the account. |
| `call <method> [json]` | Calls any method with raw params. |

## Compatibility

The Publisher runs this SDK from its repository while each adapter pins a release, so the Publisher talks to adapters on older releases.

- Changes to requests, results, errors and `adapter.toml` must be backward compatible: add optional fields, never rename or remove them.
- Bump `version` in `pyproject.toml` with every change to `src/` (CI checks), and tag the release `sdk-vX.Y.Z`.

## Release an adapter

Push a version tag such as `v1.2.0`. The Publisher installs and updates adapters by tag.
