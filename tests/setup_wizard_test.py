"""First-run setup assistant integration tests."""

import os
import sqlite3
import sys
import tempfile

sys.path.insert(0, "/app")
database_file = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
database_file.close()
os.environ["DATABASE_PATH"] = database_file.name
os.environ["SECRET_KEY"] = "setup-test-secret"
os.environ["STORNO_PASSWORT"] = "setup-password"
os.environ["UPDATE_CHECKER_ENABLED"] = "false"

try:
    from app import app

    client = app.test_client()
    response = client.get("/setup")
    assert response.status_code == 200
    page = response.get_data(as_text=True)
    assert "/setup/complete" in page and "/setup/test/" in page

    response = client.post(
        "/setup/complete",
        data={
            "language": "en",
            "currency": "AUD",
            "admin_name": "Setup Admin",
            "admin_login": "setup-admin",
            "admin_password": "1234",
            "product_ean": "12345678",
            "product_name": "Setup Cola",
            "product_stock": "6",
            "product_price": "2.50",
        },
    )
    assert response.status_code == 302
    conn = sqlite3.connect(database_file.name)
    settings = dict(conn.execute(
        "SELECT schluessel, wert FROM einstellungen WHERE schluessel IN "
        "('setup_completed','default_currency','language','benutzerkonten_aktiv')"
    ))
    assert settings == {
        "benutzerkonten_aktiv": "1",
        "default_currency": "AUD",
        "language": "en",
        "setup_completed": "1",
    }
    assert conn.execute("SELECT COUNT(*) FROM benutzer WHERE rolle='admin'").fetchone()[0] == 1
    assert conn.execute("SELECT bestand FROM produkte WHERE name='Setup Cola'").fetchone()[0] == 6
    conn.close()
    assert client.get("/setup").status_code == 302
    print("All setup wizard tests passed.")
finally:
    os.unlink(database_file.name)
