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

# Backup schedule normalization and due-time calculation.
backup_settings = {
    "backup_enabled": "1",
    "backup_frequency": "daily",
    "backup_time": "03:00",
    "backup_weekday": "0",
    "backup_max_backups": "7",
    "backup_max_age_days": "30",
    "last_backup": "2026-08-01T03:00:00",
    "last_backup_status": "success",
    "last_backup_error": "",
}
original_backup_get_setting = backup.get_setting
backup.get_setting = lambda key, default=None: backup_settings.get(key, default)
schedule = backup.backup_schedule(
    backup.datetime.fromisoformat("2026-08-02T04:00:00")
)
assert schedule["due"] and schedule["max_backups"] == 7
backup_settings["backup_frequency"] = "weekly"
backup_settings["backup_weekday"] = "6"
weekly = backup.backup_schedule(
    backup.datetime.fromisoformat("2026-08-02T02:00:00")
)
assert weekly["next_backup"].hour == 3 and weekly["weekday"] == 6

# Invalid settings are normalized, short intervals use the last successful run,
# and disabled schedules never become due.
backup_settings["backup_frequency"] = "invalid"
backup_settings["backup_time"] = "99:99"
backup_settings["backup_max_backups"] = "invalid"
normalized = backup.backup_schedule(
    backup.datetime.fromisoformat("2026-08-02T04:00:00")
)
assert normalized["frequency"] == "daily"
assert normalized["time"] == "03:00"
assert normalized["max_backups"] == 30
backup_settings["backup_frequency"] = "6h"
backup_settings["last_backup"] = "2026-08-02T01:00:00"
interval = backup.backup_schedule(
    backup.datetime.fromisoformat("2026-08-02T04:00:00")
)
assert interval["next_backup"].hour == 7 and not interval["due"]
backup_settings["last_backup"] = "not-a-date"
assert backup.backup_schedule()["next_backup"] is not None
backup_settings["backup_enabled"] = "0"
disabled = backup.backup_schedule()
assert disabled["next_backup"] is None and not disabled["due"]
assert backup._parse_time(None) == (3, 0)

# Managed backup success/failure persists useful status and scheduled runs only
# execute when due.
managed_settings = {
    "backup_enabled": "1", "backup_frequency": "6h",
    "last_backup": "", "backup_path": "/data/backups",
}
backup.get_setting = lambda key, default=None: managed_settings.get(key, default)
backup.set_setting = lambda key, value: managed_settings.__setitem__(key, str(value))
original_create_backup = backup.create_backup
original_cleanup_backups = backup.cleanup_backups
backup.create_backup = lambda *args, **kwargs: {"filename": "managed.db"}
backup.cleanup_backups = lambda *args, **kwargs: ["expired.db"]
managed = backup.create_managed_backup("automatic")
assert managed["deleted"] == ["expired.db"]
assert managed_settings["last_backup_status"] == "success"
backup.create_backup = Mock(side_effect=RuntimeError("disk full"))
try:
    backup.create_managed_backup()
except RuntimeError:
    pass
else:
    raise AssertionError("Managed backup failure was swallowed")
assert managed_settings["last_backup_status"] == "failed"
backup.create_backup = original_create_backup
backup.cleanup_backups = original_cleanup_backups
backup.get_setting = original_backup_get_setting


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
update_settings = {}
docker_update.get_setting = lambda key, default=None: update_settings.get(key, default)
docker_update.set_setting = lambda key, value: update_settings.__setitem__(key, str(value))
requests_seen = []


def fake_docker_request(method, path, body=None):
    requests_seen.append((method, path, body))
    if path.startswith("/containers/json"):
        return [
            {
                "Image": docker_update.EXPECTED_IMAGE + ":latest",
                "Names": ["/smart-drink-fridge-web"],
            },
            {
                "Image": docker_update.EXPECTED_IMAGE + ":latest",
                "Names": ["/smart-drink-fridge-scanner"],
            },
            {"Image": "unrelated:latest", "Names": ["/other"]},
        ]
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
create_body = next(body for method, path, body in requests_seen if path.startswith("/containers/create"))
assert "smart-drink-fridge-web" in create_body["Cmd"]
assert "smart-drink-fridge-scanner" in create_body["Cmd"]
original_managed_container_names = docker_update.managed_container_names
docker_update.managed_container = lambda: {"Image": "sha256:new"}
docker_update.managed_container_names = lambda: [
    "smart-drink-fridge-web", "smart-drink-fridge-scanner"
]
docker_update.docker_request = lambda method, path, body=None: {
    "Image": "sha256:old" if "scanner" in path else "sha256:new"
}
assert docker_update.companion_update_needed()
assert update_settings["update_install_status"] == "running"
assert docker_update.decode_docker_logs(b"plain log") == "plain log"

# Multiplexed Docker output and update phases shown in the settings page.
payload = b"checking image\n"
frame = b"\x01\x00\x00\x00" + len(payload).to_bytes(4, "big") + payload
assert docker_update.decode_docker_logs(frame) == "checking image\n"


def update_status_for(state, logs="", stored="running", started="2026-08-02T10:00:00"):
    update_settings.clear()
    update_settings.update({
        "update_install_status": stored,
        "update_install_started_at": started,
        "update_install_target": "9.9.9",
        "update_install_error": "",
    })

    def status_request(method, path, body=None):
        if "/logs?" in path:
            return logs
        return {"State": state}

    docker_update.docker_request = status_request
    return docker_update.docker_update_status()


assert update_status_for({"Status": "created"})["phase"] == "preparing"
assert update_status_for({"Status": "running"}, "checking images")["phase"] == "checking"
assert update_status_for({"Status": "running"}, "pulling new image")["phase"] == "downloading"
assert update_status_for({"Status": "running"}, "stopping container")["phase"] == "restarting"
assert update_status_for({"Status": "exited", "ExitCode": 0})["phase"] == "reconnecting"
failed_update = update_status_for({"Status": "dead", "ExitCode": 2}, "permission denied")
assert failed_update["status"] == "failed" and "permission denied" in failed_update["error"]

# Missing helpers remain reconnectable briefly, but stale jobs fail clearly.
docker_update.docker_request = Mock(side_effect=RuntimeError("missing"))
recent = docker_update.datetime.now().isoformat(timespec="seconds")
update_settings.update({
    "update_install_status": "starting", "update_install_started_at": recent,
    "update_install_target": "9.9.9", "update_install_error": "",
})
assert docker_update.docker_update_status()["status"] == "running"
old = (docker_update.datetime.now() - docker_update.timedelta(minutes=30)).isoformat()
update_settings["update_install_started_at"] = old
assert docker_update.docker_update_status()["status"] == "failed"

# Discovery tolerates unavailable companions and falls back to the web container.
docker_update.managed_container = lambda: {"Name": "/fallback", "Image": "sha256:new"}
docker_update.docker_request = lambda method, path, body=None: []
docker_update.managed_container_names = original_managed_container_names
assert docker_update.managed_container_names() == ["fallback"]
docker_update.managed_container_names = lambda: ["missing", "same"]
docker_update.docker_request = lambda method, path, body=None: (
    (_ for _ in ()).throw(RuntimeError("gone"))
    if "missing" in path else {"Image": "sha256:new"}
)
assert not docker_update.companion_update_needed()

docker_update.docker_request = lambda method, path, body=None: {
    "State": {"Status": "running"}
}
assert docker_update.docker_update_in_progress()
running_status = docker_update.docker_update_status()
assert running_status["status"] == "running"
docker_update.docker_update_available = lambda: True
assert docker_update.start_docker_update() is False
update_settings["update_install_target"] = "v" + docker_update.CURRENT_VERSION
assert docker_update.docker_update_status()["status"] == "success"
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
