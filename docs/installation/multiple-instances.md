# Multiple instances

To run a second Publisher on the same host, give it its own install directory, instance name and ports:

1. Install it without nginx. When it shares a database or RabbitMQ server with the first instance, also pass `--db-name acme --db-user acme` or `--broker-vhost acme --broker-user acme`; reusing the first instance's user would give it a new password and break the first instance:

   ```bash
   sudo ./install.sh --install-dir /srv/relaysms-acme --instance-name acme --skip-nginx
   ```

2. Set free `PORT` and `GRPC_PORT` values in `/srv/relaysms-acme/.env`. The installer gives every instance 16000 and 6000.

3. Restart it, then put nginx in front:

   ```bash
   cd /srv/relaysms-acme
   sudo ./manage.sh restart
   sudo ./manage.sh nginx acme.example.com
   ```

Its units are named after the instance (`relaysms-publisher-acme.target`, `relaysms-publisher-acme-rest.service`, ...), and the `manage.sh` in each install directory manages only its own instance. Running `install.sh` again on that directory reuses the name; a different `--instance-name` is refused.
