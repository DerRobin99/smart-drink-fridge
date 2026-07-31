"""Unit tests for backup, update, notification, and status services."""

import os
import sqlite3
import sys
import time
from pathlib import Path
from unittest.mock import Mock

sys.path.insert(0, "/app")
os.environ.setdefault("SECRET_KEY", "ci-services-secret")

import backup
import docker_update
from utils import notifications, system_status


# Backup validation, integrity, creation, listing, and retention.
backup_dir = Path("/data/ci-service-backups")
backup_dir.mkdir(parents=True, exist_ok=True)
database = Path("/data/ci-service-source.db")
connection = sqlite3.connect(database)
connection.execute("CREATE TABLE sample (value TEXT)")
connection.execute("INSERT INTO sample VALUES ('ok')")
connection.commit()
connection.close()

try:
    try:
        backup.validate_backup_path("/tmp/not-allowed")
    except ValueError:
        pass
    else:
        raise AssertionError("Unsafe backup path accepted")

    assert backup.test_backup_path(backup_dir)["writable"]
    assert backup.check_database("/data/missing.db")[0] is False
    assert backup.check_database(database) == (True, "ok")
    created = backup.create_backup(database, backup_dir, "CI")
    assert created["integrity_ok"] and created["comment"] == "CI"
    assert backup.list_backups(backup_dir)[0]["filename"] == created["filename"]

    older = backup_dir / "older.db"
    oldest = backup_dir / "oldest.db"
    older.write_bytes(b"old")
    oldest.write_bytes(b"oldest")
    old_time = time.time() - 120 * 86400
    os.utime(oldest, (old_time, old_time))
    deleted = backup.cleanup_backups(backup_dir, max_backups=2, max_age_days=90)
    assert "oldest.db" in deleted
finally:
    for file in backup_dir.glob("*"):
        file.unlink()
    backup_dir.rmdir()
    database.unlink(missing_ok=True)


# Pushover secrets, fallback settings, event filtering, and HTTP outcomes.
settings = {}
notifications.get_setting = lambda key, default=None: settings.get(key, default)
notifications.set_setting = lambda key, value: settings.__setitem__(key, str(value))
encrypted = notifications.encrypt_secret("secret-value")
assert notifications.decrypt_secret(encrypted) == "secret-value"
assert notifications.decrypt_secret("broken") == ""
notifications.save_pushover_credentials("user-key", "app-token")
assert notifications.get_pushover_credentials() == ("user-key", "app-token", "database")
assert notifications.pushover_configured() == (True, "database")
settings["pushover_enabled"] = "1"
settings["pushover_event_removed"] = "1"
assert notifications.notification_enabled("removed")
assert not notifications.notification_enabled("unknown-event")

response = Mock()
response.raise_for_status.return_value = None
notifications.requests.post = Mock(return_value=response)
assert notifications.send_pushover("removed", "title", "message") == (True, "sent")
notifications.requests.post = Mock(side_effect=notifications.requests.RequestException("offline"))
assert notifications.send_pushover("removed", "title", "message", force=True)[1] == "request_failed"
notifications.save_pushover_credentials(clear=True)
assert notifications.get_pushover_credentials() == ("", "", "")
assert notifications.send_pushover("removed", "title", "message", force=True)[1] == "missing_credentials"


# Docker API behavior and one-click update orchestration.
os.environ["DOCKER_UPDATE_ENABLED"] = "true"
docker_update.os.path.exists = lambda path: True
requests_seen = []


def fake_docker_request(method, path, body=None):
    requests_seen.append((method, path, body))
    if path.startswith("/containers/smart-drink-fridge-web/json"):
        return {"Name": "/smart-drink-fridge-web", "Config": {"Image": docker_update.EXPECTED_IMAGE + ":latest"}}
    if path == f"/containers/{docker_update.HELPER_NAME}/json":
        raise RuntimeError("missing")
    if path.startswith("/containers/create"):
        return {"Id": "helper-id"}
    return None


docker_update.docker_request = fake_docker_request
assert docker_update.docker_update_available()
assert not docker_update.docker_update_in_progress()
assert docker_update.start_docker_update()
assert any(path == "/containers/helper-id/start" for _, path, _ in requests_seen)

docker_update.docker_request = lambda method, path, body=None: {
    "State": {"Status": "running"}
}
assert docker_update.docker_update_in_progress()
docker_update.docker_update_available = lambda: True
assert docker_update.start_docker_update() is False
os.environ["DOCKER_UPDATE_ENABLED"] = "false"
docker_update.docker_update_available = lambda: False
assert not docker_update.docker_update_available()


# System helpers and Docker container/camera discovery.
assert system_status._format_bytes(1024) == "1.0 KB"
assert system_status._format_duration(65) == "1m"
assert system_status._format_duration(3660) == "1h 1m"
assert system_status._format_duration(90000).startswith("1d")
assert system_status._memory_status() is not None
assert system_status._uptime() is not None
assert system_status._database_status()["path"]


def status_docker_request(method, path):
    if path.startswith("/containers/json"):
        return [
            {"Id": "web", "Names": ["/smart-drink-fridge-web"], "Image": "image", "State": "running", "Status": "Up"},
            {"Id": "scanner", "Names": ["/smart-drink-fridge-scanner"], "Image": "image", "State": "running", "Status": "Up"},
            {"Id": "other", "Names": ["/unrelated"], "Image": "image", "State": "running", "Status": "Up"},
        ]
    return {"HostConfig": {"Devices": [{"PathOnHost": "/dev/video0"}]}}


system_status.docker_request = status_docker_request
containers = system_status._container_status()
assert containers["available"] and len(containers["containers"]) == 2
assert containers["camera"] == {"configured": True, "running": True}
status = system_status.get_system_status()
assert status["hostname"] and status["containers"]["available"]
system_status.docker_request = Mock(side_effect=RuntimeError("no socket"))
assert not system_status._container_status()["available"]

print("All service unit tests passed.")
