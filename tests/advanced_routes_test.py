"""Integration tests for accounts, settings, backups, and integrations."""

import os
import shutil
import sqlite3
import sys
import tempfile
from pathlib import Path
from unittest.mock import Mock

sys.path.insert(0, "/app")
db_file = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
db_file.close()
os.environ["DATABASE_PATH"] = db_file.name
os.environ["SECRET_KEY"] = "ci-advanced-secret"
os.environ["STORNO_PASSWORT"] = "ci-admin"
os.environ["UPDATE_CHECKER_ENABLED"] = "false"


def expect(response, status):
    assert response.status_code == status, (response.request.path, response.status_code)


try:
    from app import app
    import routes.home_assistant as home_assistant
    import routes.settings as settings_routes

    app.config.update(TESTING=True)
    client = app.test_client()

    expect(client.get("/einstellungen/benutzer"), 200)
    expect(client.post("/einstellungen/benutzer/aktivieren", data={"setup_password": "wrong"}), 302)
    expect(
        client.post(
            "/einstellungen/benutzer/aktivieren",
            data={"name": "Admin", "login_name": "admin", "password": "1234", "setup_password": "ci-admin"},
        ),
        302,
    )
    expect(client.get("/einstellungen/benutzer"), 200)
    expect(client.post("/einstellungen/benutzer/anlegen", data={"name": ""}), 302)
    expect(
        client.post(
            "/einstellungen/benutzer/anlegen",
            data={"name": "User", "login_name": "user", "password": "5678", "rolle": "invalid", "rfid": "A1B2C3D4"},
        ),
        302,
    )
    # Duplicate login exercises transaction rollback.
    expect(
        client.post(
            "/einstellungen/benutzer/anlegen",
            data={"name": "Duplicate", "login_name": "user", "password": "5678"},
        ),
        302,
    )
    enrollment = client.post("/einstellungen/benutzer/rfid-anlernen/start")
    expect(enrollment, 200)
    token = enrollment.get_json()["token"]
    expect(client.get(f"/einstellungen/benutzer/rfid-anlernen/status?token={token}"), 200)
    expect(client.post("/einstellungen/benutzer/999/rfid-zuordnen", data={"token": "bad"}), 400)
    expect(client.post("/einstellungen/benutzer/scanner-regel", data={"required": "1"}), 302)

    conn = sqlite3.connect(db_file.name)
    user_id = conn.execute("SELECT id FROM benutzer WHERE login_name='user'").fetchone()[0]
    cursor = conn.execute(
        "INSERT INTO buchungen (ean, produkt, aktion, menge, quelle) VALUES ('x', 'Cola', 'Ausgebucht', -1, 'web')"
    )
    booking_id = cursor.lastrowid
    conn.commit()
    conn.close()
    expect(client.post(f"/einstellungen/benutzer/buchung/{booking_id}/zuordnen", data={"benutzer_id": user_id}), 302)
    expect(client.get(f"/einstellungen/benutzer/{user_id}/statistik?zeitraum=all"), 200)

    # Notification settings validation, storage, display, test, and clearing.
    expect(client.get("/einstellungen/benachrichtigungen"), 200)
    expect(client.post("/einstellungen/benachrichtigungen", data={"pushover_user": "short"}), 302)
    key = "A" * 30
    token_value = "B" * 30
    expect(
        client.post(
            "/einstellungen/benachrichtigungen",
            data={"pushover_user": key, "pushover_token": token_value, "pushover_enabled": "on", "event_removed": "on"},
        ),
        302,
    )
    expect(client.get("/einstellungen/benachrichtigungen"), 200)
    settings_routes.send_pushover = lambda *args, **kwargs: (True, "sent")
    expect(client.post("/einstellungen/benachrichtigungen/test"), 302)
    expect(client.post("/einstellungen/benachrichtigungen", data={"clear_credentials": "1"}), 302)

    expect(client.get("/einstellungen/system"), 200)
    expect(
        client.post(
            "/einstellungen",
            data={
                "backup_enabled": "on",
                "backup_frequency": "weekly",
                "backup_time": "04:30",
                "backup_weekday": "2",
                "backup_max_backups": "12",
                "backup_max_age_days": "45",
            },
        ),
        302,
    )
    expect(client.get("/einstellungen"), 200)
    expect(client.get("/einstellungen/update-status"), 200)
    expect(client.post("/einstellungen/update-pruefen"), 302)
    expect(client.post("/einstellungen/update-installieren"), 302)

    # Home Assistant disabled/configuration/error/success and list routes.
    expect(client.post("/api/home-assistant/shopping-list/sync"), 400)
    conn = sqlite3.connect(db_file.name)
    conn.executemany(
        "INSERT INTO einstellungen (schluessel, wert) VALUES (?, ?) ON CONFLICT(schluessel) DO UPDATE SET wert=excluded.wert",
        [("ha_einkaufsliste_aktiv", "1"), ("ha_url", "http://ha"), ("ha_token", "token")],
    )
    conn.execute("INSERT INTO produkte (name, bestand, mindestbestand, sollbestand) VALUES ('Water', 0, 1, 5)")
    conn.commit()
    conn.close()
    expect(client.get("/api/home-assistant/shopping-list"), 200)
    response = Mock()
    response.raise_for_status.return_value = None
    home_assistant.requests.post = Mock(return_value=response)
    expect(client.post("/api/home-assistant/shopping-list/sync"), 200)
    expect(client.post("/api/home-assistant/shopping-list/sync"), 200)
    home_assistant.requests.post = Mock(side_effect=home_assistant.requests.RequestException("offline"))
    conn = sqlite3.connect(db_file.name)
    conn.execute("UPDATE produkte SET sollbestand=6 WHERE name='Water'")
    conn.commit()
    conn.close()
    expect(client.post("/api/home-assistant/shopping-list/sync"), 502)

    # Backup route lifecycle against the container's isolated /data database.
    data_db = Path("/data/getraenke.db")
    shutil.copyfile(db_file.name, data_db)
    backup_dir = Path("/data/advanced-route-backups")
    backup_dir.mkdir(exist_ok=True)
    conn = sqlite3.connect(db_file.name)
    conn.execute("UPDATE einstellungen SET wert=? WHERE schluessel='backup_path'", (str(backup_dir),))
    conn.commit()
    conn.close()
    expect(client.post("/settings/backup/create"), 302)
    filename = next(backup_dir.glob("*.db")).name
    expect(client.get(f"/settings/backup/download/{filename}"), 200)
    expect(client.get("/settings/backup/download/missing.db"), 302)
    expect(client.post(f"/settings/backup/restore/{filename}"), 302)
    expect(client.post(f"/settings/backup/delete/{filename}"), 302)
    expect(client.post("/settings/backup/delete/missing.db"), 302)
    for file in backup_dir.glob("*"):
        file.unlink()
    backup_dir.rmdir()
    data_db.unlink(missing_ok=True)

    expect(client.post("/abmelden"), 302)
    expect(client.get("/"), 302)
    expect(client.get("/anmelden"), 200)
    expect(client.post("/anmelden", data={"login_name": "admin", "password": "bad"}), 302)
    expect(client.post("/anmelden?next=//evil", data={"login_name": "admin", "password": "1234"}), 302)
    expect(client.post("/einstellungen/benutzer/deaktivieren"), 302)

    print("All advanced route tests passed.")
finally:
    os.unlink(db_file.name)
