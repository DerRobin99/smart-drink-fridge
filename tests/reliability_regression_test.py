"""Regression tests for backup safety and consistent stock booking."""

import os
import sqlite3
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, "/app")

data_directory = tempfile.TemporaryDirectory(dir="/data")
database_file = Path(data_directory.name) / "fridge.db"
backup_directory = Path(data_directory.name) / "backups"
os.environ["DATABASE_PATH"] = str(database_file)
os.environ["SECRET_KEY"] = "ci-reliability-secret"
os.environ["UPDATE_CHECKER_ENABLED"] = "false"

try:
    from app import app
    from backup import create_backup
    import routes.home_assistant as home_assistant
    import scanner_booking
    from werkzeug.security import generate_password_hash

    app.config.update(TESTING=True)
    admin_client = app.test_client()
    user_client = app.test_client()

    conn = sqlite3.connect(database_file)
    conn.executemany(
        """
        INSERT INTO benutzer (name, login_name, password_hash, rolle, aktiv)
        VALUES (?, ?, ?, ?, 1)
        """,
        [
            ("Admin", "admin", generate_password_hash("admin-pass"), "admin"),
            ("User", "user", generate_password_hash("user-pass"), "user"),
        ],
    )
    conn.executemany(
        """
        INSERT INTO einstellungen (schluessel, wert) VALUES (?, ?)
        ON CONFLICT(schluessel) DO UPDATE SET wert=excluded.wert
        """,
        [
            ("benutzerkonten_aktiv", "1"),
            ("backup_path", str(backup_directory)),
            ("backup_max_backups", "1"),
            ("backup_max_age_days", "0"),
            ("restore_marker", "from-backup"),
        ],
    )
    conn.commit()
    conn.close()

    assert admin_client.post(
        "/anmelden",
        data={"login_name": "admin", "password": "admin-pass"},
    ).status_code == 302
    assert user_client.post(
        "/anmelden",
        data={"login_name": "user", "password": "user-pass"},
    ).status_code == 302

    selected_backup = create_backup(database_file, backup_directory, "selected")
    selected_path = Path(selected_backup["path"])
    conn = sqlite3.connect(database_file)
    conn.execute(
        "UPDATE einstellungen SET wert='changed' WHERE schluessel='restore_marker'"
    )
    conn.commit()
    conn.close()

    for method, path in (
        (user_client.post, "/settings/backup/create"),
        (user_client.get, f"/settings/backup/download/{selected_path.name}"),
        (user_client.post, f"/settings/backup/delete/{selected_path.name}"),
        (user_client.post, f"/settings/backup/restore/{selected_path.name}"),
    ):
        assert method(path).status_code == 403

    response = admin_client.post(
        f"/settings/backup/restore/{selected_path.name}"
    )
    assert response.status_code == 302
    assert selected_path.is_file()
    conn = sqlite3.connect(database_file)
    assert conn.execute(
        "SELECT wert FROM einstellungen WHERE schluessel='restore_marker'"
    ).fetchone()[0] == "from-backup"

    conn.execute(
        "UPDATE einstellungen SET wert='1' WHERE schluessel='checkout_mode_enabled'"
    )
    product_id = conn.execute(
        """
        INSERT INTO produkte (
            name, bestand, mindestbestand, sollbestand, preis_cent, waehrung
        ) VALUES ('Cola', 7, 1, 8, 150, 'EUR')
        """
    ).lastrowid
    second_location = conn.execute(
        "INSERT INTO standorte (name, aktiv) VALUES ('Garage', 1)"
    ).lastrowid
    conn.execute(
        """
        INSERT OR REPLACE INTO standort_bestaende (
            produkt_id, standort_id, bestand, mindestbestand, sollbestand
        ) VALUES (?, 1, 4, 1, 8)
        """,
        (product_id,),
    )
    conn.execute(
        """
        INSERT INTO standort_bestaende (
            produkt_id, standort_id, bestand, mindestbestand, sollbestand
        ) VALUES (?, ?, 3, 1, 8)
        """,
        (product_id, second_location),
    )
    conn.execute(
        """
        INSERT INTO produkt_barcodes (ean, produkt_id, menge, aktion)
        VALUES ('checkout-code', ?, 1, 'entnehmen'),
               ('scanner-code', ?, 1, 'entnehmen')
        """,
        (product_id, product_id),
    )
    conn.commit()
    conn.close()

    assert user_client.post(
        "/checkout/remove",
        data={"product_id": product_id, "quantity": 2},
    ).status_code == 302
    conn = sqlite3.connect(database_file)
    assert conn.execute(
        "SELECT bestand FROM standort_bestaende WHERE produkt_id=? AND standort_id=1",
        (product_id,),
    ).fetchone()[0] == 2
    assert conn.execute(
        "SELECT bestand FROM standort_bestaende WHERE produkt_id=? AND standort_id=?",
        (product_id, second_location),
    ).fetchone()[0] == 3
    assert conn.execute(
        "SELECT bestand FROM produkte WHERE id=?", (product_id,)
    ).fetchone()[0] == 5
    booking_location = conn.execute(
        "SELECT standort_id FROM buchungen WHERE quelle='checkout' ORDER BY id DESC"
    ).fetchone()[0]
    assert booking_location == 1
    conn.close()

    sync_calls = []
    home_assistant.sync_home_assistant_shopping_list_data = (
        lambda: sync_calls.append("synced")
    )
    result = scanner_booking.book_barcode(
        "scanner-code",
        source="ios-app",
        return_details=True,
        user_id=2,
        user_name="User",
    )
    assert result["ok"]
    assert sync_calls == ["synced"]

    print("All reliability regression tests passed.")
finally:
    data_directory.cleanup()
