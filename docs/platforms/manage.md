# Managing adapters

Each platform, such as Gmail, is served by an adapter installed from its own GitHub repository.

Run these commands from the install directory with [`publisher.sh`](../operating/services.md#publishersh), which runs them as the service user.

## Commands

| Command | Does |
| --- | --- |
| `platforms add <GITHUB_URL> [--tag <TAG>]` | Installs the newest version tag, or `<TAG>` |
| `platforms update [<NAME>] [--tag <TAG>]` | Moves one adapter, or all, to a version tag |
| `platforms list` | Lists every adapter, disabled ones included |
| `platforms disable <NAME>` | Hides it from users; linked accounts can still be unlinked |
| `platforms enable <NAME>` | Offers it again |
| `platforms remove <NAME> [--force]` | Uninstalls it ([details](#removing)) |
| `platforms config show <NAME>` | Lists its settings, without secret values |
| `platforms config set <NAME> <KEY>=<VALUE>\|<KEY>` | Changes settings; a bare `<KEY>` asks for its value |
| `platforms setup <NAME> [--input <KEY>=<VALUE>]` | Runs the adapter's setup and saves its settings |
| `platforms import` | Registers adapter directories on disk that the database lacks, and moves their files out of the code ([details](../operating/upgrading.md#adapter-registry-import)) |
| `platforms exec <NAME> -- <COMMAND>` | Runs a command the adapter installs |

Prefix each with `sudo ./publisher.sh`, for example:

```bash
sudo ./publisher.sh platforms add https://github.com/smswithoutborders/gmail-oauth2-adapter
```

Commands taking a name also take `--proto-id` and `--cat-id`, for when a name matches more than one adapter. Administrators can do the same over the [REST API](../reference/rest-api.md#managing-platform-adapters), but only from GitHub orgs listed in `PLATFORMS_GITHUB_ORGS`.

## Versions

Adapters are installed and updated by version tag, such as `v1.2.0`, so a repository needs one before it can be added.

An update builds the new version and its virtualenv beside the running one, then switches over, so a failed update leaves the running version in place. An update is refused if the installed tag now points to a different commit: publish a new tag instead of moving one.

## Removing

`remove` is refused while accounts are linked through the adapter, since their tokens can only be revoked through it. Disable the adapter instead.

> [!WARNING]
> `--force` removes it anyway and leaves those tokens unrevocable.

## Files

| Directory | Holds |
| --- | --- |
| `PLATFORMS_ADAPTERS_DIR/<ID>` | The adapter's code at its tag, replaced on every update |
| `PLATFORMS_ADAPTERS_VENV_DIR/<ID>` | Its virtualenv |
| `PLATFORMS_ADAPTERS_CONFIG_DIR/<ID>` | Its `credentials.json` |
| `PLATFORMS_ADAPTERS_STATE_DIR/<ID>` | What it writes, such as databases |

`<ID>` is the ID column of `platforms list`.

## Settings

An adapter reads its settings, such as API keys, from `credentials.json` in its config directory. Its `adapter.toml` declares each one. Lists are comma-separated.

```bash
sudo ./publisher.sh platforms config set rmail smtp_host=smtp.example.com smtp_port=465
sudo ./publisher.sh platforms config set rmail smtp_password
sudo ./publisher.sh platforms config set rmail --unset alias_prefix
```

`config set` changes only the keys given. `setup` is for adapters whose settings come from the platform, such as a registered app for Mastodon or a downloaded client file for Gmail, and replaces all of them. `--input <KEY>=@<PATH>` reads a file as the service user, from the install directory, so give an absolute path it can read:

```bash
sudo ./publisher.sh platforms setup gmail --input client_file=@/tmp/client_secret.json
```

## Redirect URIs

OAuth2 adapters, such as Gmail, send the user back to a redirect URI after they authorize. The client app chooses it and sends it to the Publisher when it links an account; the adapter uses the first of its `redirect_uris` setting when the app sends none.

1. Run an HTTPS page that receives the authorization `code` and `state` and hands them back to the app.
2. Configure the apps to send that page's URI.
3. Register the same URI, character for character, with the platform. A trailing slash counts.
4. Set it in the adapter's `redirect_uris`, with every other URI your apps send.

## Provider guides

| Platform | Adapter | Protocol |
| --- | --- | --- |
| [Gmail](gmail.md) | [gmail-oauth2-adapter](https://github.com/smswithoutborders/gmail-oauth2-adapter) | OAuth2 |
| [Mastodon](mastodon.md) | [mastodon-oauth2-adapter](https://github.com/smswithoutborders/mastodon-oauth2-adapter) | OAuth2 |
| [Bluesky](bluesky.md) | [bluesky-oauth2-adapter](https://github.com/smswithoutborders/bluesky-oauth2-adapter) | OAuth2 |
| [Telegram](telegram.md) | [telegram-pnba-adapter](https://github.com/smswithoutborders/telegram-pnba-adapter) | Phone number |
| [RelaySMS Mail](relaysms-mail.md) | [relaysms-mail-pnba-adapter](https://github.com/smswithoutborders/relaysms-mail-pnba-adapter) | Phone number |

## An adapter's own commands

An adapter may install admin commands. `exec` runs one from the adapter's virtualenv with its config and state directories; put `--` before it:

```bash
sudo ./publisher.sh platforms exec <NAME> -- <COMMAND> --help
```

## Next steps

- Follow the [provider guide](#provider-guides) for each platform you offer, then link a test account from the RelaySMS app.
- To support another platform, see [Writing an adapter](../developers/writing-an-adapter.md).
