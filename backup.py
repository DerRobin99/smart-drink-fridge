from __future__ import annotations

import os
import shutil
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path


ALLOWED_BACKUP_ROOTS = (
    Path("/data").resolve(),
    Path("/host-mnt").resolve(),
)


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

    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    destination = destination_dir / f"{database.stem}_{timestamp}.db"

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
