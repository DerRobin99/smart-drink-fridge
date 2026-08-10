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
    import routes.setup as setup_routes

    client = app.test_client()
    app.config["TESTING"] = False
    assert client.get("/").status_code == 302
    response = client.get("/setup")
    assert response.status_code == 200
    page = response.get_data(as_text=True)
    assert "/setup/complete" in page and "/setup/test/" in page

    setup_routes.get_system_status = lambda: {
        "containers": {"camera": {"configured": True, "running": True}, "containers": []}
    }
    assert client.post("/setup/test/scanner").get_json()["ok"] is True
    setup_routes._test_beep = lambda: None
    assert client.post("/setup/test/beep").status_code == 200
    setup_routes._test_beep = lambda: (_ for _ in ()).throw(RuntimeError("offline"))
    assert client.post("/setup/test/beep").status_code == 503
    assert client.post("/setup/test/unknown").status_code == 404
    assert client.post("/setup/complete", data={
        "admin_name": "", "admin_login": "", "admin_password": "x"
    }).status_code == 302

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
            "ha_url": "http://homeassistant.local/",
            "ha_token": "ha-token",
            "pushover_user": "push-user",
            "pushover_token": "push-token",
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
    assert client.post("/setup/test/scanner").status_code == 404
    print("All setup wizard tests passed.")
finally:
    os.unlink(database_file.name)
