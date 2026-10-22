# Install with Docker

`docker-compose.yml` runs every service in one container, with its data in `./data` and its settings in `.env` (`template.env` describes each one):

```bash
git clone --recurse-submodules https://github.com/smswithoutborders/RelaySMS-Publisher.git
cd RelaySMS-Publisher
make .env
docker compose up -d --build
```

The container applies pending migrations, then starts every service. It publishes `PORT` (16000) and `GRPC_PORT` (6000) on every interface. To serve it publicly, bind them to `127.0.0.1` in `docker-compose.yml` and put [nginx with TLS](reverse-proxy.md#by-hand) in front.

Run the admin CLI with `docker compose exec publisher python -m publisher <command>`.

Back up `.env` with `./data`: its [encryption keys](../configuration/encryption-keys.md) are the only way to read the data.

## Updating

```bash
git pull --recurse-submodules
docker compose up -d --build
```
