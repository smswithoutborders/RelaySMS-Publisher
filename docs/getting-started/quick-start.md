# Quick start

Runs the Publisher on your machine with Docker, to try it before installing it on a server. You need Git, Docker with the Compose plugin, `make` and `openssl`.

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
   docker compose exec publisher python -m publisher creds create --username admin --administrator
   ```

   > [!IMPORTANT]
   > The password is printed once. Store it before closing the terminal.

6. Use it on the REST API:

   ```bash
   curl -u admin:<PASSWORD> http://localhost:16000/v1/auth/me
   ```

   You should see `"username":"admin"` and `"administrator":true`.

To stop the Publisher, run `docker compose down`. To start again from scratch, also run `sudo rm -rf data .env`.

## Next steps

- [Add a platform](../platforms/manage.md)
- [Register a gateway client](../gateway-clients/manage.md)
- [Install on a server](../installation/server.md) for production

Those pages run the admin CLI as `sudo ./publisher.sh`; with Docker, use `docker compose exec publisher python -m publisher` instead.
