# JOBHUNTER AI

JOBHUNTER AI is a containerized React + FastAPI foundation backed by MySQL 8.4, Redis, and Celery. The project currently provides platform health checks and the scaffolding for the next product phase; it does not yet implement job-search features.

## Start in development

1. Copy `.env.development.example` to `.env` and replace both database passwords and `SECRET_KEY` with local values.
2. Run `docker compose --env-file .env -f compose.yml up --build` from this directory.
3. Open `http://localhost:8080`. The API readiness check is at `/api/health/ready`.

The first backend start applies Alembic migrations. MySQL data and Redis persistence are stored in named Docker volumes. MySQL and Redis have no published host ports; only Nginx is exposed.

Create the first administrator interactively after the backend is running; no default password is provided:

```sh
docker compose --env-file .env exec backend python -m app.cli create-admin --email admin@example.com
```

## Production HTTPS

Copy `.env.production.example` to a secret-managed `.env`, set unique strong credentials, and place a valid `fullchain.pem` and `privkey.pem` under `certs/`. Start with `docker compose --env-file .env -f compose.yml -f compose.prod.yml up --build -d`. Production Nginx redirects HTTP to HTTPS. Do not commit real environment files or certificates.

For a production deployment, also configure backups, host firewall rules, domain-specific `server_name`, TLS renewal, monitoring, and an external secret manager. The included templates are examples, not deployable secrets.

## Useful commands

```sh
# Apply migrations manually
docker compose --env-file .env exec backend alembic upgrade head

# View service status and logs
docker compose --env-file .env ps
docker compose --env-file .env logs -f backend worker scheduler

# Stop services (named volumes are preserved)
docker compose --env-file .env down

# Create a consistent MySQL backup
docker compose --env-file .env exec backend python scripts/backup.py /tmp/backups
```

## Stack

- Frontend: React, TypeScript, Vite
- API: FastAPI, SQLAlchemy 2, Alembic, PyMySQL
- Database: MySQL 8.4 (`jobhunter_db`)
- Queue and cache: Redis, Celery worker and Beat scheduler
- Edge: Nginx with a separate HTTPS production configuration

See [DEVELOPMENT.md](./DEVELOPMENT.md) for architecture and contributor workflow.
