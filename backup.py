from __future__ import annotations

import os
import shutil
import sqlite3
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path

from database import DB, get_setting, set_setting


ALLOWED_BACKUP_ROOTS = (
    Path("/data").resolve(),
    Path("/host-mnt").resolve(),
)
BACKUP_FREQUENCIES = {
    "6h": timedelta(hours=6),
    "12h": timedelta(hours=12),
    "daily": timedelta(days=1),
    "weekly": timedelta(days=7),
}
_scheduler_thread = None
_scheduler_lock = threading.Lock()
_backup_operation_lock = threading.Lock()


def validate_backup_path(backup_dir: str | Path) -> Path:
    path = Path(backup_dir).expanduser().resolve()

    if not any(path == root or root in path.parents for root in ALLOWED_BACKUP_ROOTS):
        raise ValueError(
            "Backup-Pfad muss unter /data oder /host-mnt liegen."
        )

    path.mkdir(parents=True, exist_ok=True)

    if not path.is_dir():
        raise ValueError("Backup-Pfad ist kein Verzeichnis.")

    test_file = path / ".backup_write_test"

    try:
        test_file.write_text("ok", encoding="utf-8")
        test_file.unlink()
    except OSError as exc:
        raise PermissionError(
            f"Backup-Pfad ist nicht beschreibbar: {exc}"
        ) from exc

    return path


def test_backup_path(backup_dir: str | Path) -> dict:
    path = validate_backup_path(backup_dir)
    usage = shutil.disk_usage(path)

    return {
        "path": str(path),
        "writable": True,
        "free_bytes": usage.free,
        "total_bytes": usage.total,
    }


def check_database(database_path: str | Path) -> tuple[bool, str]:
    database = Path(database_path).resolve()

    if not database.is_file():
        return False, "Datenbankdatei wurde nicht gefunden."

    connection = sqlite3.connect(
        f"file:{database}?mode=ro",
        uri=True,
        timeout=30,
    )

    try:
        result = connection.execute("PRAGMA integrity_check").fetchone()
        message = result[0] if result else "Keine Antwort"
        return message == "ok", message
    finally:
        connection.close()


def create_backup(
    database_path: str | Path,
    backup_dir: str | Path = "/data/backups",
    comment: str | None = None,
) -> dict:
    database = Path(database_path).resolve()
    destination_dir = validate_backup_path(backup_dir)

    if not database.is_file():
        raise FileNotFoundError(
            f"Datenbank wurde nicht gefunden: {database}"
        )

    integrity_ok, integrity_message = check_database(database)

    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S-%f")
    destination = destination_dir / f"smart-drink-fridge_{timestamp}.db"

    source_connection = sqlite3.connect(
        f"file:{database}?mode=ro",
        uri=True,
        timeout=30,
    )
    destination_connection = sqlite3.connect(destination)

    try:
        source_connection.backup(destination_connection)
    except Exception:
        destination_connection.close()
        source_connection.close()
        destination.unlink(missing_ok=True)
        raise
    else:
        destination_connection.close()
        source_connection.close()

    if not destination.is_file() or destination.stat().st_size == 0:
        destination.unlink(missing_ok=True)
        raise RuntimeError("Backup-Datei wurde nicht korrekt erstellt.")

    return {
        "filename": destination.name,
        "path": str(destination),
        "size_bytes": destination.stat().st_size,
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "comment": comment or "",
        "integrity_ok": integrity_ok,
        "integrity_message": integrity_message,
    }


def list_backups(
    backup_dir: str | Path = "/data/backups",
) -> list[dict]:
    path = validate_backup_path(backup_dir)
    backups = []

    for file in path.glob("*.db"):
        if not file.is_file():
            continue

        stat = file.stat()
        backups.append(
            {
                "filename": file.name,
                "path": str(file),
                "size_bytes": stat.st_size,
                "created_at": datetime.fromtimestamp(
                    stat.st_mtime
                ).isoformat(timespec="seconds"),
            }
        )

    return sorted(
        backups,
        key=lambda item: item["created_at"],
        reverse=True,
    )


def cleanup_backups(
    backup_dir: str | Path = "/data/backups",
    max_backups: int = 30,
    max_age_days: int = 90,
) -> list[str]:
    path = validate_backup_path(backup_dir)
    files = sorted(
        (file for file in path.glob("*.db") if file.is_file()),
        key=lambda file: file.stat().st_mtime,
        reverse=True,
    )

    delete_files: set[Path] = set()

    if max_backups > 0:
        delete_files.update(files[max_backups:])

    if max_age_days > 0:
        cutoff = datetime.now() - timedelta(days=max_age_days)

        for file in files:
            modified = datetime.fromtimestamp(file.stat().st_mtime)

            if modified < cutoff:
                delete_files.add(file)

    deleted = []

    for file in delete_files:
        file.unlink(missing_ok=True)
        deleted.append(file.name)

    return sorted(deleted)


def _setting_int(key: str, default: int, minimum: int, maximum: int) -> int:
    try:
        value = int(get_setting(key, str(default)))
    except (TypeError, ValueError):
        value = default
    return min(maximum, max(minimum, value))


def _parse_time(value: str) -> tuple[int, int]:
    try:
        hour, minute = (int(part) for part in value.split(":", 1))
    except (AttributeError, TypeError, ValueError):
        return 3, 0
    if not 0 <= hour <= 23 or not 0 <= minute <= 59:
        return 3, 0
    return hour, minute


def _parse_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return None


def backup_schedule(now: datetime | None = None) -> dict:
    """Return normalized automatic-backup settings and next execution."""
    now = now or datetime.now()
    enabled = str(get_setting("backup_enabled", "1")).lower() in {
        "1", "true", "yes", "on"
    }
    frequency = get_setting("backup_frequency", "daily")
    if frequency not in BACKUP_FREQUENCIES:
        frequency = "daily"
    backup_time = get_setting("backup_time", "03:00")
    hour, minute = _parse_time(backup_time)
    weekday = _setting_int("backup_weekday", 0, 0, 6)
    last_backup = _parse_datetime(get_setting("last_backup", ""))

    if frequency in {"6h", "12h"}:
        next_backup = (
            last_backup + BACKUP_FREQUENCIES[frequency]
            if last_backup
            else now
        )
    elif frequency == "daily":
        scheduled_today = now.replace(
            hour=hour,
            minute=minute,
            second=0,
            microsecond=0,
        )
        next_backup = scheduled_today
        if last_backup and last_backup >= scheduled_today:
            next_backup += timedelta(days=1)
        elif now < scheduled_today:
            next_backup = scheduled_today
    else:
        days_ahead = (weekday - now.weekday()) % 7
        scheduled = (now + timedelta(days=days_ahead)).replace(
            hour=hour,
            minute=minute,
            second=0,
            microsecond=0,
        )
        if scheduled <= now and (not last_backup or last_backup < scheduled):
            next_backup = scheduled
        elif scheduled <= now:
            next_backup = scheduled + timedelta(days=7)
        else:
            next_backup = scheduled

    return {
        "enabled": enabled,
        "frequency": frequency,
        "time": f"{hour:02d}:{minute:02d}",
        "weekday": weekday,
        "max_backups": _setting_int("backup_max_backups", 30, 1, 365),
        "max_age_days": _setting_int("backup_max_age_days", 90, 0, 3650),
        "last_backup": last_backup,
        "last_status": get_setting("last_backup_status", ""),
        "last_error": get_setting("last_backup_error", ""),
        "next_backup": next_backup if enabled else None,
        "due": enabled and next_backup <= now,
    }


def create_managed_backup(comment: str | None = None) -> dict:
    """Create a backup, apply retention, and persist its result."""
    schedule = backup_schedule()
    backup_path = get_setting("backup_path", "/data/backups")
    try:
        with _backup_operation_lock:
            result = create_backup(DB, backup_path, comment)
            deleted = cleanup_backups(
                backup_path,
                max_backups=schedule["max_backups"],
                max_age_days=schedule["max_age_days"],
            )
    except Exception as exc:
        set_setting("last_backup_status", "failed")
        set_setting("last_backup_error", str(exc)[:500])
        raise

    completed_at = datetime.now().isoformat(timespec="seconds")
    set_setting("last_backup", completed_at)
    set_setting("last_backup_status", "success")
    set_setting("last_backup_error", "")
    return {**result, "deleted": deleted}


def run_scheduled_backup(now: datetime | None = None) -> dict | None:
    schedule = backup_schedule(now)
    if not schedule["due"]:
        return None
    return create_managed_backup("automatic")


def _backup_scheduler_loop(poll_seconds: int = 30) -> None:
    while True:
        try:
            run_scheduled_backup()
        except Exception:
            # The detailed error is persisted by create_managed_backup and is
            # visible in settings. The loop must survive transient failures.
            pass
        time.sleep(poll_seconds)


def start_backup_scheduler() -> bool:
    """Start the single background scheduler used by the web container."""
    global _scheduler_thread
    if os.getenv("BACKUP_SCHEDULER_ENABLED", "true").lower() not in {
        "1", "true", "yes", "on"
    }:
        return False

    with _scheduler_lock:
        if _scheduler_thread and _scheduler_thread.is_alive():
            return False
        _scheduler_thread = threading.Thread(
            target=_backup_scheduler_loop,
            name="backup-scheduler",
            daemon=True,
        )
        _scheduler_thread.start()
    return True
