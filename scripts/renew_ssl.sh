#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="${1:-/opt/jobhunter-ai}"
DOMAIN="jobs.jkdesignke.com"

cd "$PROJECT_DIR"
mkdir -p ./certbot/www ./certs

certbot renew --webroot -w "$PROJECT_DIR/certbot/www" --quiet

cp -L "/etc/letsencrypt/live/${DOMAIN}/fullchain.pem" "$PROJECT_DIR/certs/fullchain.pem"
cp -L "/etc/letsencrypt/live/${DOMAIN}/privkey.pem" "$PROJECT_DIR/certs/privkey.pem"
chmod 644 "$PROJECT_DIR/certs/fullchain.pem"
chmod 600 "$PROJECT_DIR/certs/privkey.pem"

docker compose --env-file .env -f compose.yml -f compose.prod.yml exec -T nginx nginx -s reload
