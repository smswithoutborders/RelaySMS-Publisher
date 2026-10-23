# Quick start

Runs the Publisher on your machine with Docker, to try it before installing it on a server.

## Requirements

- **Docker with the Compose plugin**: [Docker Engine](https://docs.docker.com/engine/install/) on Linux, or [Docker Desktop](https://docs.docker.com/desktop/), which includes Compose, on macOS and Windows. On Linux, [add yourself to the `docker` group](https://docs.docker.com/engine/install/linux-postinstall/) or prefix the `docker` commands with `sudo`.
- **Git, `make` and `openssl`**: on macOS, `xcode-select --install` provides Git and `make`, and `openssl` ships with the system. On Windows, run the steps in [WSL](https://learn.microsoft.com/en-us/windows/wsl/install). On Ubuntu or Debian:

  ```bash
  sudo apt-get install -y git make openssl
  ```

Check them:

```bash
docker compose version
git --version
make --version
openssl version
```

## Steps

1. Clone the repository with its submodule:

   ```bash
   git clone --recurse-submodules https://github.com/smswithoutborders/RelaySMS-Publisher.git
   cd RelaySMS-Publisher
   ```

2. Create `.env` with fresh encryption keys:

   ```bash
   make .env
   ```

3. Build and start. The first build compiles the payload library in Rust and takes several minutes:

   ```bash
   docker compose up -d --build
   ```

4. Check that it's up:

   ```bash
   curl http://localhost:16000/health
   ```

   You should see `{"status":"ok"}`. If the connection fails, the container is still applying migrations; `docker compose logs -f` shows its progress.

5. Create an administrator credential:

   ```bash
   docker compose exec publisher \
     python -m publisher creds create --username admin --administrator
   ```

   > [!IMPORTANT]
   > The password is printed only once.

6. Use it on the REST API:

   ```bash
   curl -u admin:<PASSWORD> http://localhost:16000/v1/auth/me
   ```

   You should see `"username":"admin"` and `"administrator":true`.

To stop the Publisher, run `docker compose down`. To start again from scratch, also run `sudo rm -rf data .env`.

## Next steps

The pages below run the admin CLI as `sudo ./publisher.sh`; with Docker, use `docker compose exec publisher python -m publisher` instead.

- [Add a platform](../platforms/manage.md)
- [Register a gateway client](../gateway-clients/manage.md)
- [Install on a server](../installation/server.md) for production
