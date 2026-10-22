# Reverse proxy and TLS

The services listen on `127.0.0.1`. nginx serves them on port 443 with a Let's Encrypt certificate, from [the site template](https://github.com/smswithoutborders/RelaySMS-Publisher/blob/main/deploy/nginx/relaysms-publisher-nginx.conf.template). It sends `/publisher.v3.Publisher` and `/grpc.health.v1.Health` to gRPC on `GRPC_PORT`, and everything else to REST on `PORT`, and rate-limits logins and requests carrying HTTP Basic credentials.

## With the installer

Pass `--site-name DOMAIN` to the [installer](server.md#run-the-installer). Running it again leaves an existing site file alone, and skips Certbot when the domain already has a certificate; use [`manage.sh nginx`](#on-an-existing-install) to render the site again.

## On an existing install

`manage.sh nginx` renders the site from the template, obtains or reattaches its certificate, and turns on HTTP/2, which gRPC needs. Run it to add nginx later, or after an update that changes the template. It keeps the previous file as `<site>.conf.bak` and restores it if the new one fails.

```bash
sudo apt-get install -y nginx certbot python3-certbot-nginx
sudo ./manage.sh nginx publisher.example.com
```

## By hand

With nginx and Certbot installed as above:

```bash
sudo sed -e "s/__SERVER_NAME__/publisher.example.com/g" \
    -e "s/__REST_PORT__/16000/g" -e "s/__GRPC_PORT__/6000/g" \
    deploy/nginx/relaysms-publisher-nginx.conf.template |
    sudo tee /etc/nginx/sites-available/publisher.example.com.conf >/dev/null
sudo ln -s /etc/nginx/sites-available/publisher.example.com.conf /etc/nginx/sites-enabled/
sudo nginx -t && sudo systemctl reload nginx
sudo certbot --nginx -d publisher.example.com --redirect
```

Then turn on HTTP/2 in the HTTPS block Certbot added: add `http2 on;` after `listen 443 ssl;` (nginx 1.25.1 or newer), or change it to `listen 443 ssl http2;`. Reload nginx.

## gRPC TLS without nginx

The gRPC server can serve TLS itself. The REST API can't, so it still needs a reverse proxy.

```bash
GRPC_HOST=0.0.0.0
GRPC_TLS_ENABLED=true
GRPC_TLS_CERT_FILE=/path/to/fullchain.pem
GRPC_TLS_KEY_FILE=/path/to/privkey.pem
```
