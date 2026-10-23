# Writing an adapter

An adapter publishes to one platform. It's a Python package in its own repository, built with the [RelaySMS Adapter SDK](https://github.com/smswithoutborders/RelaySMS-Publisher/tree/main/sdk), which the Publisher runs in its own virtualenv and calls over JSON-RPC.

## Requirements

- Python 3.12 or newer
- A GitHub repository
- A developer account and API credentials for the platform

## Steps

1. Copy the SDK's [echo adapter](https://github.com/smswithoutborders/RelaySMS-Publisher/tree/main/sdk/examples/echo-adapter) into a new repository named after the platform and protocol, such as `example-oauth2-adapter`.
2. Subclass the SDK's base class for its protocol, such as `OAuth2Adapter`, and implement its methods ([Write an adapter](https://github.com/smswithoutborders/RelaySMS-Publisher/tree/main/sdk#write-an-adapter)).
3. Describe it in `adapter.toml`: its name, protocol, category, and a `[config]` table for each setting ([Describe it](https://github.com/smswithoutborders/RelaySMS-Publisher/tree/main/sdk#describe-it)).
4. Try it with the `relaysms-adapter` console, which runs it the way the Publisher does ([Try it](https://github.com/smswithoutborders/RelaySMS-Publisher/tree/main/sdk#try-it)).
5. Tag a release, such as `v1.0.0` ([Release an adapter](https://github.com/smswithoutborders/RelaySMS-Publisher/tree/main/sdk#release-an-adapter)).
6. Install it on a Publisher:

   ```bash
   sudo ./publisher.sh platforms add https://github.com/<ORG>/<REPOSITORY>
   ```

7. Set its settings with `sudo ./publisher.sh platforms config set <NAME> <KEY>=<VALUE>`, or `platforms setup <NAME>` if it has a setup ([Settings](../platforms/manage.md#settings)).

## Check it

`sudo ./publisher.sh platforms list` shows the adapter with its tag, and ✓ under Configured once its settings are set. Then link a test account from the RelaySMS app.

The adapters in the [provider guides](../platforms/manage.md#provider-guides), such as [gmail-oauth2-adapter](https://github.com/smswithoutborders/gmail-oauth2-adapter), are complete examples.
