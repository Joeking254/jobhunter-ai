# Development guide

## Layout

- `backend/app/api/routes`: HTTP routes, including liveness and readiness.
- `backend/app/core`: environment-backed settings and structured JSON logging.
- `backend/app/db`: SQLAlchemy declarative base, engine, pooled sessions, and request transaction dependency.
- `backend/app/worker`: Celery worker app and scheduled heartbeat placeholder.
- `backend/migrations`: Alembic environment and initial infrastructure-only baseline.
- `frontend/src`: React application and styles.
- `nginx`: local HTTP and production HTTPS reverse-proxy configurations.

## Local workflow

Use Docker Compose as the supported full-stack environment. Keep credentials in a local `.env` copied from the development template. Never commit `.env`, private certificates, or database files. The Compose `data` network is internal and only application services can reach MySQL and Redis; neither service publishes a host port.

Create schema changes as Alembic revisions from `backend/` and review generated migrations before applying them. API database dependencies wrap each request in a transaction: successful requests commit; exceptions roll back. The engine enables connection pre-ping, bounded pooling, overflow limits, timeouts, and connection recycling.

Structured application logs are one JSON object per line on stdout/stderr. Set `LOG_LEVEL` to adjust verbosity. `/api/health/live` checks process liveness; `/api/health/ready` checks MySQL and Redis and returns 503 if a dependency is unavailable.

## Security notes

Application containers run as non-root users where supported, drop Linux capabilities, and enable `no-new-privileges`. Backend and worker filesystems are read-only with temporary storage mounted at `/tmp`. Nginx is the only service with published ports. Production requires valid certificates and externally managed secrets; replace example values before startup.
