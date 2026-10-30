# Optional public HTTPS

Administrative recipe for Ubuntu 24.04 and the fresh-server setup in [INSTALL.md](INSTALL.md). It does not change firewall, SSH or DNS settings automatically. Do not apply it over an existing reverse proxy without reviewing its configuration.

Each deployment remains a separate MCP process, bearer token, cache, worker and browser pool. A shared nginx frontend does not merge their authentication or data. One public IP can serve `/alice/mcp` and `/bob/mcp`; separate hostnames can each use `/mcp`.

## 1. Prerequisites and private backend

- Complete private deployment and checks first. Bind MCP to `127.0.0.1`.
- Use your public IPv4 address or a DNS hostname pointing at the server. Any published AAAA record must also reach this server.
- Arrange inbound TCP 80/443, IPv4 and IPv6 as appropriate; preserve SSH access. Docker-published ports can bypass UFW: publish only MCP on loopback; publish no search/storage/control/worker ports.
- Run these commands as administrator from the deployment checkout. Use a lowercase `PUBLIC_HOST`; substitute your actual instance ID for `alice`.

```sh
export PUBLIC_HOST=YOUR_PUBLIC_IP_OR_DNS_NAME
python3 scripts/render_proxy.py --origin "https://$PUBLIC_HOST" --path /alice/mcp
```

The helper validates origin/path, reserves the public endpoint against another initialized deployment, and creates `.state/alice.http.conf` and `.state/alice.location.conf`. It refuses overwrites and does not install or reload nginx. Inspect both files. Endpoint reservations persist across stops/reboots.

## 2. HTTP challenge and certificate

```sh
apt-get update
apt-get install -y nginx gettext-base python3-venv
python3 -m venv /opt/research-certbot
/opt/research-certbot/bin/pip install 'certbot==5.8.0'
install -d -m 755 /var/www/letsencrypt
```

Back up any affected nginx files. On a fresh nginx installation, remove the default site's enabled symlink only if it is unused. Render/install the challenge-only site first; a TLS site cannot load before its certificate exists:

```sh
envsubst '${PUBLIC_HOST}' < infra/nginx-bootstrap.conf.example > ".state/$PUBLIC_HOST.bootstrap.conf"
install -m 644 ".state/$PUBLIC_HOST.bootstrap.conf" "/etc/nginx/sites-available/research-mcp-$PUBLIC_HOST"
ln -s "/etc/nginx/sites-available/research-mcp-$PUBLIC_HOST" "/etc/nginx/sites-enabled/research-mcp-$PUBLIC_HOST"
nginx -t && systemctl reload nginx
```

Verify `http://PUBLIC_HOST/.well-known/acme-challenge/` is reachable from outside after placing a harmless test file there. Remove it afterward. Certificate issuance is an explicit external operation: provide your own email, review the CA terms, and choose **one** command:

```sh
# DNS hostname:
/opt/research-certbot/bin/certbot certonly --webroot -w /var/www/letsencrypt \
  --cert-name "research-mcp-$PUBLIC_HOST" -d "$PUBLIC_HOST" \
  --email YOUR_EMAIL --agree-tos --non-interactive

# Public IPv4 address (short-lived certificate):
/opt/research-certbot/bin/certbot certonly --webroot -w /var/www/letsencrypt \
  --cert-name "research-mcp-$PUBLIC_HOST" --ip-address "$PUBLIC_HOST" \
  --preferred-profile shortlived --email YOUR_EMAIL --agree-tos --non-interactive
```

Never use a self-signed certificate for ordinary public clients or disable client TLS verification. Disposable VM tests use their own explicitly trusted test CA, not production issuance.

## 3. Install the proxy

Install instance snippets into the directory for their public host. Multiple instances sharing that host get distinct exact paths and independent rate/connection-limit zones.

```sh
install -d -m 755 "/etc/nginx/research-mcp/$PUBLIC_HOST"
install -m 644 .state/alice.http.conf .state/alice.location.conf "/etc/nginx/research-mcp/$PUBLIC_HOST/"
# Create this global include ONCE per server, not once per public hostname:
printf 'include /etc/nginx/research-mcp/*/*.http.conf;\n' > /etc/nginx/conf.d/research-mcp-zones.conf
envsubst '${PUBLIC_HOST}' < infra/nginx-research.conf.example > ".state/$PUBLIC_HOST.tls.conf"
install -m 644 ".state/$PUBLIC_HOST.tls.conf" "/etc/nginx/sites-available/research-mcp-$PUBLIC_HOST"
nginx -t && systemctl reload nginx
```

An instance snippet exposes only its exact MCP path; the backend receives `/mcp`. Authorization passes through unchanged. Host is rewritten to the expected loopback backend only after the public server's Host check. Origin is accepted only when absent or exactly the configured HTTPS origin, then cleared before forwarding. Other paths return 404. Limits are 10 requests/second with burst 20, 10 connections per IP per deployment, a 1 MiB proxy request ceiling (the MCP server's own limit is lower), and 180-second proxy timeouts. Buffering is disabled. Do not add a static bearer token to nginx.

Check externally: trusted TLS, unknown Host rejection, unrelated path 404, missing/incorrect bearer rejection, untrusted Origin rejection, and an authenticated 34-tool discovery/health call. For two instances, each token must fail against the other endpoint. Do not print tokens in shell commands or logs.

## 4. Renewal

Install the following root-owned files after reviewing any existing Certbot automation. Use only one renewal schedule for this Certbot installation. The six-hour schedule matters for short-lived IP certificates.

`/etc/systemd/system/research-certbot-renew.service`:

```ini
[Unit]
Description=Renew research HTTPS certificates
Wants=network-online.target
After=network-online.target
[Service]
Type=oneshot
ExecStart=/opt/research-certbot/bin/certbot renew --quiet
```

`/etc/systemd/system/research-certbot-renew.timer`:

```ini
[Unit]
Description=Check research HTTPS certificate renewal
[Timer]
OnCalendar=*-*-* 00,06,12,18:00:00
RandomizedDelaySec=900
Persistent=true
[Install]
WantedBy=timers.target
```

`/etc/letsencrypt/renewal-hooks/deploy/reload-research-nginx` (root-owned, executable):

```sh
#!/bin/sh
set -eu
/usr/sbin/nginx -t
/usr/bin/systemctl reload nginx
```

```sh
systemctl daemon-reload
systemctl enable --now research-certbot-renew.timer
/opt/research-certbot/bin/certbot renew --dry-run --run-deploy-hooks
systemctl list-timers research-certbot-renew.timer
```

Inspect renewal logs and certificate expiry periodically; a timer being enabled is not proof of successful renewal. Failed nginx validation must prevent reload. Certificate issuance and renewal require public CA/network availability and are not proved by a private VM test.
