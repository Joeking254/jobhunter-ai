import ctypes
from datetime import datetime, timedelta, timezone
import os
from pathlib import Path
import shutil
import time
from typing import Any

from redis import Redis
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.session import engine
from app.models.models import Application, BotRun, SourceExecutionHistory
from app.worker.control import get_worker_health_and_queues


def _memory_stats() -> dict[str, Any]:
    # Linux /proc/meminfo (Ubuntu 24.04 & Docker containers)
    meminfo = Path("/proc/meminfo")
    if meminfo.is_file():
        values: dict[str, int] = {}
        for line in meminfo.read_text(encoding="utf-8").splitlines():
            parts = line.split(":")
            if len(parts) == 2:
                num = parts[1].strip().split()[0]
                if num.isdigit():
                    values[parts[0]] = int(num)
        total_kb = values.get("MemTotal", 0)
        avail_kb = values.get("MemAvailable", values.get("MemFree", 0))
        used_kb = max(0, total_kb - avail_kb)
        pct = round((used_kb / total_kb) * 100, 1) if total_kb else 0.0
        return {
            "total_mb": round(total_kb / 1024, 1),
            "used_mb": round(used_kb / 1024, 1),
            "used_pct": pct,
        }

    # Windows fallback via GlobalMemoryStatusEx
    if os.name == "nt":
        class MEMORYSTATUSEX(ctypes.Structure):
            _fields_ = [
                ("dwLength", ctypes.c_ulong),
                ("dwMemoryLoad", ctypes.c_ulong),
                ("ullTotalPhys", ctypes.c_ulonglong),
                ("ullAvailPhys", ctypes.c_ulonglong),
                ("ullTotalPageFile", ctypes.c_ulonglong),
                ("ullAvailPageFile", ctypes.c_ulonglong),
                ("ullTotalVirtual", ctypes.c_ulonglong),
                ("ullAvailVirtual", ctypes.c_ulonglong),
                ("sullAvailExtendedVirtual", ctypes.c_ulonglong),
            ]

        stat = MEMORYSTATUSEX()
        stat.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
        if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(stat)):  # type: ignore[attr-defined]
            total_mb = round(stat.ullTotalPhys / (1024 * 1024), 1)
            used_mb = round((stat.ullTotalPhys - stat.ullAvailPhys) / (1024 * 1024), 1)
            return {"total_mb": total_mb, "used_mb": used_mb, "used_pct": float(stat.dwMemoryLoad)}

    return {"total_mb": 0.0, "used_mb": 0.0, "used_pct": 0.0}


def _cpu_stats() -> dict[str, Any]:
    cpu_count = os.cpu_count() or 1
    load_1m = None
    if hasattr(os, "getloadavg"):
        try:
            load_1m = round(os.getloadavg()[0], 2)
        except OSError:
            load_1m = None
    return {
        "cpu_count": cpu_count,
        "load_1m": load_1m,
        "load_pct_estimate": round(min(100.0, ((load_1m or 0.0) / cpu_count) * 100), 1) if load_1m is not None else None,
    }


def _disk_stats(path_str: str) -> dict[str, Any]:
    target = Path(path_str)
    probe = target if target.exists() else Path(".")
    usage = shutil.disk_usage(probe)
    total_gb = round(usage.total / (1024**3), 2)
    used_gb = round(usage.used / (1024**3), 2)
    free_gb = round(usage.free / (1024**3), 2)
    used_pct = round((usage.used / usage.total) * 100, 1) if usage.total else 0.0
    return {"total_gb": total_gb, "used_gb": used_gb, "free_gb": free_gb, "used_pct": used_pct}


def collect_monitoring_summary(
    db: Session,
    *,
    redis_factory=None,
) -> dict[str, Any]:
    cutoff = datetime.now(timezone.utc) - timedelta(hours=24)

    db_start = time.monotonic()
    db_status = "ok"
    try:
        db.execute(text("SELECT 1"))
    except Exception:
        db_status = "error"
    db_latency_ms = round((time.monotonic() - db_start) * 1000, 2)

    redis_start = time.monotonic()
    redis_status = "ok"
    try:
        client = (redis_factory or (lambda: Redis.from_url(settings.redis_url, socket_connect_timeout=2, socket_timeout=2)))()
        try:
            client.ping()
        finally:
            client.close()
    except Exception:
        redis_status = "error"
    redis_latency_ms = round((time.monotonic() - redis_start) * 1000, 2)

    if db_status == "ok":
        worker_health = get_worker_health_and_queues(db, redis_factory=redis_factory)
        failed_tasks_24h = int(
            db.scalar(select(func.count(BotRun.id)).where(BotRun.status == "failed", BotRun.started_at >= cutoff)) or 0
        )
        source_failures_24h = int(
            db.scalar(
                select(func.count(SourceExecutionHistory.id)).where(
                    SourceExecutionHistory.status == "failed",
                    SourceExecutionHistory.started_at >= cutoff,
                )
            )
            or 0
        )
        application_failures_24h = int(
            db.scalar(
                select(func.count(Application.id)).where(
                    Application.status == "failed",
                    Application.updated_at >= cutoff,
                )
            )
            or 0
        )
    else:
        worker_health = {
            "redis_status": "ok" if redis_status == "ok" else "unavailable",
            "shutting_down": False,
            "workers": [],
            "last_db_heartbeat_at": None,
            "queue_depths": {},
            "active_tasks": [],
        }
        failed_tasks_24h = 0
        source_failures_24h = 0
        application_failures_24h = 0

    return {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "system": {
            "cpu": _cpu_stats(),
            "memory": _memory_stats(),
            "disk": _disk_stats(settings.document_storage_dir),
        },
        "services": {
            "database": {"status": db_status, "latency_ms": db_latency_ms},
            "redis": {"status": redis_status, "latency_ms": redis_latency_ms},
            "workers": worker_health,
        },
        "failures_24h": {
            "failed_tasks": failed_tasks_24h,
            "source_failures": source_failures_24h,
            "application_failures": application_failures_24h,
        },
    }
