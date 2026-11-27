# Backup Guide

## 1. Automated Scheduled Backups

Celery Beat runs `app.worker.tasks.scheduled_database_backup` once every 24 hours on the `maintenance` queue.

- Backups are written to `BACKUP_DIR` (`/data/backups` on the `backups_data` Docker volume in production) as gzip-compressed SQL dumps (`jobhunter_YYYYMMDDTHHMMSSZ.sql.gz`) alongside a `.sha256` checksum sidecar.
- Old backups exceeding `BACKUP_RETENTION_DAYS` (default `14`) are automatically pruned after each successful backup.

## 2. Manual Backup

```bash
cd /opt/jobhunter-ai
docker compose --env-file .env -f compose.yml -f compose.prod.yml exec backend \
  python scripts/backup.py backup /data/backups --retention-days 14
```

## 3. Copy Backups Offsite

Sync the `backups_data` volume and `documents_data` volume to encrypted offsite storage (e.g., S3/B2/rsync):

```bash
mkdir -p /var/backups/jobhunter
docker compose --env-file .env -f compose.yml -f compose.prod.yml cp backend:/data/backups/. /var/backups/jobhunter/
```

## 4. Verify Integrity

```bash
sha256sum -c /var/backups/jobhunter/jobhunter_*.sql.gz.sha256
```
