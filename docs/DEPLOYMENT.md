# Production Deployment Guide (`jobs.jkdesignke.com`)

## 1. DNS & TLS Certificates

Point an `A` (and optional `AAAA`) DNS record for `jobs.jkdesignke.com` to your Ubuntu 24.04 server IP.

Obtain the initial Let's Encrypt certificate before starting production Nginx:

```bash
sudo certbot certonly --standalone -d jobs.jkdesignke.com --agree-tos -m admin@jkdesignke.com --non-interactive
mkdir -p /opt/jobhunter-ai/certs /opt/jobhunter-ai/certbot/www
sudo cp -L /etc/letsencrypt/live/jobs.jkdesignke.com/fullchain.pem /opt/jobhunter-ai/certs/fullchain.pem
sudo cp -L /etc/letsencrypt/live/jobs.jkdesignke.com/privkey.pem /opt/jobhunter-ai/certs/privkey.pem
sudo chown "$USER":"$USER" /opt/jobhunter-ai/certs/*.pem
chmod 644 /opt/jobhunter-ai/certs/fullchain.pem
chmod 600 /opt/jobhunter-ai/certs/privkey.pem
```

## 2. Build & Start Production Stack

```bash
cd /opt/jobhunter-ai
docker compose --env-file .env -f compose.yml -f compose.prod.yml up --build -d
```

This launches:
- `frontend`: Production Vite/React static build served on internal port `8080`.
- `backend`: FastAPI + Uvicorn (`APP_ENV=production`, `COOKIE_SECURE=true`, read-only root FS, `cap_drop: ALL`, `no-new-privileges`). Runs `alembic upgrade head` on startup.
- `worker`: Celery worker consuming `celery,discovery,analysis,applications,notifications,maintenance` queues with `stop_grace_period: 30s`.
- `scheduler`: Celery Beat running 6-hour discovery, daily checks, backups, and 3-minute notification retries.
- `mysql` & `redis`: Persistent named volumes (`mysql_data`, `redis_data`, `documents_data`, `backups_data`).
- `nginx`: TLS termination on `80`/`443` for `jobs.jkdesignke.com` with HSTS, CSP, and security headers.

## 3. Verify Health & Create Owner Account

```bash
curl -fsS https://jobs.jkdesignke.com/api/health/ready
docker compose --env-file .env -f compose.yml -f compose.prod.yml exec backend python -m app.cli create-admin --email owner@jkdesignke.com
```

## 4. SSL Auto-Renewal

Install a daily cron job to renew certificates and reload Nginx automatically:

```bash
chmod +x /opt/jobhunter-ai/scripts/renew_ssl.sh
(crontab -l 2>/dev/null; echo "15 3 * * * /opt/jobhunter-ai/scripts/renew_ssl.sh /opt/jobhunter-ai >> /var/log/jobhunter-ssl.log 2>&1") | crontab -
```

## 5. Dependency Vulnerability Checks

Run audits before every release:

```bash
cd /opt/jobhunter-ai/frontend && npm audit --omit=dev
cd /opt/jobhunter-ai/backend && pip check
```
