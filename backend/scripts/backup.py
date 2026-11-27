"""Create, verify, prune, and restore gzip-compressed database backups."""

import argparse
from datetime import datetime, timedelta, timezone
import gzip
import hashlib
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess

from app.core.config import settings


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        while chunk := fh.read(65536):
            digest.update(chunk)
    return digest.hexdigest()


def backup_database(
    output_dir: Path,
    *,
    retention_days: int | None = None,
    sqlite_path: Path | None = None,
) -> Path:
    """Create a compressed .sql.gz backup + .sha256 sidecar and enforce retention."""
    output_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    raw_sql = output_dir / f"jobhunter_{stamp}.sql"
    gz_path = output_dir / f"jobhunter_{stamp}.sql.gz"

    if sqlite_path is not None:
        conn = sqlite3.connect(str(sqlite_path))
        try:
            with raw_sql.open("w", encoding="utf-8") as stream:
                for line in conn.iterdump():
                    stream.write(f"{line}\n")
        finally:
            conn.close()
    else:
        command = [
            "mysqldump",
            "--single-transaction",
            "--routines",
            "--triggers",
            "--host",
            settings.mysql_host,
            "--port",
            str(settings.mysql_port),
            "--user",
            settings.mysql_user,
            settings.mysql_database,
        ]
        environment = os.environ.copy()
        environment["MYSQL_PWD"] = settings.mysql_password
        with raw_sql.open("wb") as stream:
            subprocess.run(command, stdout=stream, check=True, env=environment)

    with raw_sql.open("rb") as src, gzip.open(gz_path, "wb") as dst:
        shutil.copyfileobj(src, dst)
    raw_sql.unlink(missing_ok=True)

    checksum = _sha256_file(gz_path)
    gz_path.with_suffix(".gz.sha256").write_text(f"{checksum}  {gz_path.name}\n", encoding="utf-8")

    days = settings.backup_retention_days if retention_days is None else retention_days
    if days >= 0:
        prune_old_backups(output_dir, days)
    return gz_path


def verify_backup_checksum(backup_path: Path) -> bool:
    sidecar = backup_path.with_suffix(".gz.sha256")
    if not backup_path.is_file() or not sidecar.is_file():
        return False
    expected = sidecar.read_text(encoding="utf-8").strip().split()[0]
    return _sha256_file(backup_path) == expected


def prune_old_backups(output_dir: Path, retention_days: int) -> int:
    if not output_dir.is_dir():
        return 0
    cutoff = datetime.now(timezone.utc) - timedelta(days=retention_days)
    removed = 0
    for path in output_dir.glob("jobhunter_*.sql.gz"):
        mtime = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
        if mtime < cutoff:
            path.unlink(missing_ok=True)
            path.with_suffix(".gz.sha256").unlink(missing_ok=True)
            removed += 1
    return removed


def restore_database(backup_path: Path, *, sqlite_target: Path | None = None) -> None:
    if not verify_backup_checksum(backup_path):
        raise ValueError(f"Backup checksum verification failed for {backup_path}")
    with gzip.open(backup_path, "rt", encoding="utf-8") as src:
        sql_text = src.read()

    if sqlite_target is not None:
        sqlite_target.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(sqlite_target))
        try:
            conn.executescript(sql_text)
            conn.commit()
        finally:
            conn.close()
        return

    command = [
        "mysql",
        "--host",
        settings.mysql_host,
        "--port",
        str(settings.mysql_port),
        "--user",
        settings.mysql_user,
        settings.mysql_database,
    ]
    environment = os.environ.copy()
    environment["MYSQL_PWD"] = settings.mysql_password
    subprocess.run(command, input=sql_text.encode("utf-8"), check=True, env=environment)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="JOBHUNTER AI backup and restore tool")
    sub = parser.add_subparsers(dest="cmd")

    b_cmd = sub.add_parser("backup")
    b_cmd.add_argument("output_dir", type=Path, nargs="?", default=Path(settings.backup_dir))
    b_cmd.add_argument("--retention-days", type=int, default=settings.backup_retention_days)

    r_cmd = sub.add_parser("restore")
    r_cmd.add_argument("backup_file", type=Path)

    args = parser.parse_args()
    if args.cmd == "restore":
        restore_database(args.backup_file)
        print(f"Restored {args.backup_file}")
    else:
        out_dir = getattr(args, "output_dir", Path(settings.backup_dir))
        ret = getattr(args, "retention_days", settings.backup_retention_days)
        print(backup_database(out_dir, retention_days=ret))
