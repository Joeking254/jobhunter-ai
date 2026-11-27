# Recovery Guide

## 1. Restore MySQL from Backup

1. Stop `backend`, `worker`, and `scheduler` so no writes occur during restore:

```bash
cd /opt/jobhunter-ai
docker compose --env-file .env -f compose.yml -f compose.prod.yml stop backend worker scheduler
```

2. Verify the backup checksum and restore using `scripts/backup.py restore`:

```bash
docker compose --env-file .env -f compose.yml -f compose.prod.yml run --rm backend \
  python scripts/backup.py restore /data/backups/jobhunter_YYYYMMDDTHHMMSSZ.sql.gz
```

3. Apply any newer migrations and restart services:

```bash
docker compose --env-file .env -f compose.yml -f compose.prod.yml run --rm backend alembic upgrade head
docker compose --env-file .env -f compose.yml -f compose.prod.yml up -d
```

## 2. Redis Persistence & Recovery

Redis runs with `--appendonly yes` and `--maxmemory-policy noeviction` backed by the `redis_data` volume. If Redis restarts, workers automatically fall back to local locks during the brief outage and re-register heartbeats on reconnect. Stranded `submitting` applications are recovered automatically on worker startup (`recover_interrupted_applications`).

## 3. Alembic Migration Rollback

To roll back one revision if a deployment fails:

```bash
docker compose --env-file .env -f compose.yml -f compose.prod.yml exec backend alembic downgrade -1
```
