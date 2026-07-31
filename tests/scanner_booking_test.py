"""Tests for scanner booking behavior without camera or GPIO hardware."""

import os
import sqlite3
import sys
import tempfile
import time

sys.path.insert(0, "/app")
database_file = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
database_file.close()
os.environ["DATABASE_PATH"] = database_file.name
os.environ.setdefault("SECRET_KEY", "ci-scanner-test-secret")


class FakeBuzzer:
    def __init__(self):
        self.events = []

    def on(self):
        self.events.append("on")

    def off(self):
        self.events.append("off")


try:
    from database import init_db
    import scanner_booking

    init_db()
    notifications = []
    scanner_booking.send_pushover = lambda event, title, message: notifications.append(event)
    scanner_booking.sleep = lambda seconds: None
    buzzer = FakeBuzzer()

    conn = sqlite3.connect(database_file.name)
    conn.execute(
        """
        INSERT INTO produkte (id, name, bestand, mindestbestand, sollbestand, preis_cent, waehrung)
        VALUES (1, 'Cola', 3, 2, 8, 150, 'EUR'),
               (2, 'Water', 0, 0, 8, 80, 'EUR')
        """
    )
    conn.execute(
        """
        INSERT INTO produkt_barcodes (ean, produkt_id, menge, aktion)
        VALUES ('remove-low', 1, 1, 'entnehmen'),
               ('remove-empty', 1, 2, 'entnehmen'),
               ('too-many', 1, 99, 'entnehmen'),
               ('restock', 2, 6, 'einlagern'),
               ('invalid-action', 1, 1, 'other')
        """
    )
    conn.commit()
    conn.close()

    assert scanner_booking.book_barcode("unknown", buzzer) is False
    assert "unknown_barcode" in notifications
    assert scanner_booking.book_barcode("too-many", buzzer) is False
    assert scanner_booking.book_barcode("invalid-action", buzzer) is False

    assert scanner_booking.book_barcode("remove-low", buzzer) is True
    assert "removed" in notifications and "low_stock" in notifications
    assert scanner_booking.book_barcode("remove-empty", buzzer) is True
    assert "out_of_stock" in notifications
    assert scanner_booking.book_barcode("restock", buzzer) is True
    assert "restocked" in notifications
    assert buzzer.events.count("on") == 3

    conn = sqlite3.connect(database_file.name)
    assert conn.execute("SELECT bestand FROM produkte WHERE id = 1").fetchone()[0] == 0
    assert conn.execute("SELECT bestand FROM produkte WHERE id = 2").fetchone()[0] == 6
    assert conn.execute("SELECT COUNT(*) FROM buchungen WHERE quelle = 'scanner'").fetchone()[0] == 3

    # Requiring a user blocks scans until an active account has been selected.
    conn.execute("UPDATE einstellungen SET wert = '1' WHERE schluessel = 'benutzerkonten_aktiv'")
    conn.execute("UPDATE einstellungen SET wert = '1' WHERE schluessel = 'scanner_benutzer_erforderlich'")
    conn.execute("UPDATE produkte SET bestand = 3 WHERE id = 1")
    conn.commit()
    conn.close()
    assert scanner_booking.book_barcode("remove-low", buzzer) is False
    assert "scan_blocked" in notifications

    conn = sqlite3.connect(database_file.name)
    conn.execute(
        "INSERT INTO benutzer (id, name, login_name, password_hash, rolle, aktiv) VALUES (7, 'Robin', 'robin', 'hash', 'user', 1)"
    )
    conn.execute("UPDATE einstellungen SET wert = '7' WHERE schluessel = 'aktiver_scanner_benutzer'")
    conn.execute(
        "UPDATE einstellungen SET wert = ? WHERE schluessel = 'aktiver_scanner_benutzer_bis'",
        (str(int(time.time()) + 120),),
    )
    conn.commit()
    conn.close()
    assert scanner_booking.book_barcode("remove-low", buzzer) is True

    conn = sqlite3.connect(database_file.name)
    booking = conn.execute(
        "SELECT benutzer_id, benutzer_name FROM buchungen WHERE quelle = 'scanner' ORDER BY id DESC LIMIT 1"
    ).fetchone()
    assert booking == (7, "Robin")
    selected = conn.execute(
        "SELECT wert FROM einstellungen WHERE schluessel = 'aktiver_scanner_benutzer'"
    ).fetchone()[0]
    assert selected == ""
    conn.close()

    print("All scanner booking tests passed.")
finally:
    os.unlink(database_file.name)
