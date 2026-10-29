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

Read the [manual](docs/README.md). Its [Where to start](docs/README.md#where-to-start) table points to the page for each task.

## Contributing

Read [CONTRIBUTING.md](CONTRIBUTING.md) to set up a development checkout and open a pull request.

To add a platform, see [Writing an adapter](docs/developers/writing-an-adapter.md).

## Security

Report vulnerabilities privately, as [SECURITY.md](SECURITY.md) describes.

## License

Licensed under the GNU General Public License v3.0. See [LICENSE.md](LICENSE.md).
