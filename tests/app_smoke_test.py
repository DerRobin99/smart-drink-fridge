"""Dependency-free smoke and integration checks for the Docker image."""

from datetime import datetime, timedelta
import os
import sqlite3
import sys
import tempfile

sys.path.insert(0, "/app")


database_file = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
database_file.close()
os.environ["DATABASE_PATH"] = database_file.name
os.environ["SECRET_KEY"] = "ci-only-test-secret"
os.environ["UPDATE_CHECKER_ENABLED"] = "false"


def timestamp(days_ago, hour):
    value = datetime.now().replace(
        hour=hour,
        minute=0,
        second=0,
        microsecond=0,
    ) - timedelta(days=days_ago)
    return value.strftime("%Y-%m-%d %H:%M:%S")


try:
    from app import app
    from translation import translate

    connection = sqlite3.connect(database_file.name)
    connection.execute(
        "UPDATE einstellungen SET wert = '1' "
        "WHERE schluessel = 'benutzerkonten_aktiv'"
    )
    connection.execute(
        """
        INSERT INTO benutzer (
            id, name, login_name, password_hash, rolle, aktiv
        ) VALUES
            (1, 'Robin', 'robin', 'test', 'admin', 1),
            (2, 'Alex', 'alex', 'test', 'user', 1)
        """
    )
    connection.executemany(
        """
        INSERT INTO buchungen (
            ean, produkt, aktion, zeitpunkt, menge, quelle, storniert,
            einzelpreis_cent, waehrung, benutzer_id, benutzer_name
        ) VALUES (?, ?, 'entnehmen', ?, ?, 'scanner', ?, ?, ?, ?, ?)
        """,
        [
            ("1", "Cola", timestamp(0, 10), -2, 0, 150, "EUR", 1, "Robin"),
            ("2", "Water", timestamp(1, 20), -1, 0, 80, "EUR", 1, "Robin"),
            ("3", "Cola", timestamp(2, 2), -1, 1, 150, "EUR", 1, "Robin"),
            ("4", "Lemonade", timestamp(3, 14), -3, 0, 200, "USD", 2, "Alex"),
        ],
    )
    connection.commit()
    assert connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    connection.close()

    app.config.update(TESTING=True)
    client = app.test_client()
    with client.session_transaction() as session:
        session["user_id"] = 1

    own_statistics = client.get("/konto?zeitraum=30")
    assert own_statistics.status_code == 200
    own_html = own_statistics.get_data(as_text=True)
    for expected in (
        "Benutzerstatistik",
        "Lieblingsprodukte",
        "Verbrauchsmuster",
        "Persönliche Kosten",
        "Cola",
        "Water",
        '/static/icons/icon-192.png',
    ):
        assert expected in own_html, expected

    admin_statistics = client.get(
        "/einstellungen/benutzer/2/statistik?zeitraum=all"
    )
    assert admin_statistics.status_code == 200
    assert "Lemonade" in admin_statistics.get_data(as_text=True)

    missing_user = client.get("/einstellungen/benutzer/999/statistik")
    assert missing_user.status_code == 302

    management = client.get("/einstellungen/benutzer")
    assert management.status_code == 200
    assert (
        "/einstellungen/benutzer/2/statistik"
        in management.get_data(as_text=True)
    )

    for language in ("de", "en", "fr"):
        assert translate("user_statistics", language) != "user_statistics"
        assert translate("favorite_products", language) != "favorite_products"

    print("All application smoke and integration tests passed.")
finally:
    os.unlink(database_file.name)
