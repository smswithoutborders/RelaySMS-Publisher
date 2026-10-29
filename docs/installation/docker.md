# Install with Docker

`docker-compose.yml` runs every service in one container, with its data in `./data` and its settings in `.env` (see the [settings reference](../configuration/settings.md)). It needs the tools in the [quick start's requirements](../getting-started/quick-start.md#requirements).

```bash
git clone --recurse-submodules https://github.com/smswithoutborders/RelaySMS-Publisher.git
cd RelaySMS-Publisher
make .env
docker compose up -d --build
```

The container applies pending migrations, then starts every service. It publishes `PORT` (16000) and `GRPC_PORT` (6000) on every interface. To serve it publicly, bind them to `127.0.0.1` in `docker-compose.yml` and put [nginx with TLS](reverse-proxy.md#by-hand) in front.

Run the admin CLI with `docker compose exec publisher python -m publisher <COMMAND>`.

To update, see [Upgrading](../operating/upgrading.md#update-with-docker).

## Next steps

Continue with [After installing](server.md#after-installing) from step 3, running the CLI as `docker compose exec publisher python -m publisher`.
