"""Integration coverage for the 1.5 checkout and device-control features."""

import os
import sqlite3
import sys
import tempfile

sys.path.insert(0, "/app")
database_file = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
database_file.close()
os.environ["DATABASE_PATH"] = database_file.name
os.environ["SECRET_KEY"] = "ci-feature-150-secret"
os.environ["STORNO_PASSWORT"] = "setup-secret"
os.environ["UPDATE_CHECKER_ENABLED"] = "false"


def expect(response, status):
    assert response.status_code == status, (response.request.path, response.status_code)


try:
    from app import app
    import host_control
    import routes.settings as settings_routes
    from utils.auth import set_scanner_user

    app.config.update(TESTING=True)
    client = app.test_client()

    expect(
        client.post(
            "/einstellungen/benutzer/aktivieren",
            data={
                "name": "Admin", "login_name": "admin",
                "password": "1234", "setup_password": "setup-secret",
            },
        ),
        302,
    )
    expect(
        client.post(
            "/einstellungen",
            data={
                "default_currency": "AUD",
                "checkout_mode_enabled": "on",
                "host_control_enabled": "on",
                "display_show_user": "on",
                "display_show_booking": "on",
                "display_show_inventory": "on",
                "display_rotate_seconds": "7",
                "backup_frequency": "daily",
                "backup_time": "03:00",
                "backup_weekday": "0",
                "backup_max_backups": "30",
                "backup_max_age_days": "90",
            },
        ),
        302,
    )

    conn = sqlite3.connect(database_file.name)
    settings = dict(conn.execute(
        "SELECT schluessel, wert FROM einstellungen WHERE schluessel IN "
        "('default_currency','checkout_mode_enabled','display_show_inventory','display_rotate_seconds')"
    ).fetchall())
    assert settings == {
        "checkout_mode_enabled": "1", "default_currency": "AUD",
        "display_rotate_seconds": "7", "display_show_inventory": "1",
    }
    settings_page = client.get("/einstellungen").get_data(as_text=True)
    assert "AUD" in settings_page and "display_rotate_seconds" in settings_page
    system_page = client.get("/einstellungen/system").get_data(as_text=True)
    assert 'value="reboot"' in system_page and 'value="poweroff"' in system_page
    cursor = conn.execute(
        """
        INSERT INTO produkte
        (name, marke, bestand, mindestbestand, sollbestand, preis_cent, waehrung)
        VALUES ('Cola', 'Test Brand', 5, 1, 10, 250, 'AUD')
        """
    )
    product_id = cursor.lastrowid
    conn.execute(
        "INSERT INTO produkt_barcodes (ean, produkt_id) VALUES ('12345678', ?)",
        (product_id,),
    )
    admin_id = conn.execute(
        "SELECT id FROM benutzer WHERE login_name='admin'"
    ).fetchone()[0]
    conn.commit()
    conn.close()

    expect(client.get("/"), 302)
    expect(client.get("/checkout"), 200)
    checkout_page = client.get("/checkout").get_data(as_text=True)
    assert "Cola" in checkout_page and "5" in checkout_page
    expect(
        client.post(
            "/checkout/remove",
            data={"product_id": product_id, "quantity": 99},
        ),
        302,
    )
    expect(
        client.post(
            "/checkout/remove",
            data={"product_id": product_id, "quantity": 2},
        ),
        302,
    )
    conn = sqlite3.connect(database_file.name)
    assert conn.execute("SELECT bestand FROM produkte WHERE id=?", (product_id,)).fetchone()[0] == 3
    booking = conn.execute(
        "SELECT menge, quelle, benutzer_id FROM buchungen ORDER BY id DESC LIMIT 1"
    ).fetchone()
    conn.close()
    assert booking == (-2, "checkout", admin_id)

    # Login tiles select an account by ID without exposing its username.
    expect(client.post("/abmelden"), 302)
    login_page = client.get("/anmelden").get_data(as_text=True)
    assert 'name="user_id"' in login_page and "Admin" in login_page
    expect(
        client.post(
            "/anmelden",
            data={"user_id": admin_id, "password": "1234"},
        ),
        302,
    )

    # A physical NFC selection can move a waiting checkout kiosk into the
    # matching web session without exposing the card identifier to the browser.
    conn = sqlite3.connect(database_file.name)
    conn.execute(
        "UPDATE benutzer SET rfid_hash = 'test-digest' WHERE id = ?",
        (admin_id,),
    )
    conn.commit()
    conn.close()
    expect(client.post("/abmelden"), 302)
    set_scanner_user(admin_id, source="nfc")
    nfc_session = client.post("/api/checkout/nfc-session")
    expect(nfc_session, 200)
    assert nfc_session.get_json() == {"authenticated": True}
    expect(client.get("/checkout"), 200)

    actions = []
    settings_routes.request_host_action = lambda action: actions.append(action) or True
    expect(
        client.post(
            "/einstellungen/system/aktion",
            data={"action": "reboot", "password": "wrong"},
        ),
        302,
    )
    expect(
        client.post(
            "/einstellungen/system/aktion",
            data={"action": "reboot", "password": "1234"},
        ),
        202,
    )
    assert actions == ["reboot"]

    # The real helper uses only the current application image and a constrained
    # one-shot host namespace command.
    calls = []
    host_control.managed_container = lambda: {"Config": {"Image": "app:test"}}

    def fake_request(method, path, body=None):
        calls.append((method, path, body))
        if path.startswith("/containers/create"):
            return {"Id": "power-helper"}
        if method == "DELETE":
            raise RuntimeError("not found")
        return None

    host_control.docker_request = fake_request
    assert host_control.request_host_action("poweroff")
    create = next(body for method, path, body in calls if path.startswith("/containers/create"))
    assert create["HostConfig"]["Privileged"] is True
    assert create["HostConfig"]["PidMode"] == "host"
    assert create["Cmd"][-1] == "poweroff"
    try:
        host_control.request_host_action("invalid")
    except ValueError:
        pass
    else:
        raise AssertionError("invalid host action was accepted")

    print("All 1.5 feature tests passed.")
finally:
    os.unlink(database_file.name)
