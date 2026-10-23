# RelaySMS Publisher

Publishes to online platforms, such as Gmail, from content people send by SMS, so they can post without an internet connection. See [how it works](docs/README.md#how-it-works).

## Install

On Ubuntu 24.04 or Debian 13:

```bash
curl -fsSL https://raw.githubusercontent.com/smswithoutborders/RelaySMS-Publisher/main/install.sh \
  | sudo bash
```

[Install on a server](docs/installation/server.md) covers the installer's options and the steps after it. To try it on your machine with Docker first, follow the [quick start](docs/getting-started/quick-start.md).

## Documentation

The [manual](docs/README.md) starts with:

- [Quick start](docs/getting-started/quick-start.md)
- [Settings reference](docs/configuration/settings.md)
- [Managing adapters](docs/platforms/manage.md) and the [provider guides](docs/platforms/manage.md#provider-guides)
- [Connecting a relay](docs/gateway-clients/connect-a-relay.md)
- [Troubleshooting](docs/operating/troubleshooting.md)

`sudo ./manage.sh docs <DOMAIN>` serves the manual from your own server.

## Contributing

[CONTRIBUTING.md](CONTRIBUTING.md) covers setup, running the services locally, testing and the workflow. To start:

```bash
git clone --recurse-submodules https://github.com/smswithoutborders/RelaySMS-Publisher.git
cd RelaySMS-Publisher
make setup
```

Adapters are built with the [adapter SDK](sdk/README.md).

## Security

Report vulnerabilities privately, as [SECURITY.md](SECURITY.md) describes.

## License

Licensed under the GNU General Public License v3.0. See [LICENSE.md](LICENSE.md).
