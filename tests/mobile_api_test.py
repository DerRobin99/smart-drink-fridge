"""Integration coverage for the authenticated native mobile API."""

import os
import sqlite3
import sys
import tempfile

from werkzeug.security import generate_password_hash


sys.path.insert(0, "/app")
database_file = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
database_file.close()
os.environ["DATABASE_PATH"] = database_file.name
os.environ["SECRET_KEY"] = "ci-mobile-api-secret"
os.environ["UPDATE_CHECKER_ENABLED"] = "false"


def expect(response, status):
    assert response.status_code == status, (
        response.request.path,
        response.status_code,
        response.get_data(as_text=True)[:300],
    )


try:
    from app import app

    app.config.update(TESTING=True)
    client = app.test_client()

    expect(client.post("/api/mobile/v1/login", json={"login_name": "robin", "password": "1234"}), 409)
    conn = sqlite3.connect(database_file.name)
    conn.execute("UPDATE einstellungen SET wert='1' WHERE schluessel='benutzerkonten_aktiv'")
    conn.execute("UPDATE einstellungen SET wert='en' WHERE schluessel='language'")
    conn.execute(
        "INSERT INTO benutzer (name,login_name,password_hash,rolle) VALUES (?,?,?,?)",
        ("Robin", "robin", generate_password_hash("1234", method="pbkdf2:sha256"), "admin"),
    )
    conn.execute(
        """
        INSERT INTO produkte (name,marke,verpackungsinfo,bestand,mindestbestand,sollbestand,preis_cent,waehrung)
        VALUES ('Cola','Test','500 ml',4,2,8,149,'EUR')
        """
    )
    product_id = conn.execute("SELECT id FROM produkte WHERE name='Cola'").fetchone()[0]
    conn.execute(
        "INSERT INTO produkt_barcodes (ean,produkt_id,menge,aktion) VALUES ('4000000000001',?,1,'entnehmen')",
        (product_id,),
    )
    conn.execute(
        "INSERT OR REPLACE INTO standort_bestaende (produkt_id,standort_id,bestand,mindestbestand,sollbestand) VALUES (?,1,4,2,8)",
        (product_id,),
    )
    conn.commit()
    conn.close()

    expect(client.post("/api/mobile/v1/session"), 401)
    expect(client.post("/api/mobile/v1/login", json={"login_name": "robin", "password": "bad"}), 401)

    web_login = client.post("/anmelden?next=/dashboard", data={"user_id": "1", "password": "1234"})
    expect(web_login, 302)
    session_login = client.post("/api/mobile/v1/session")
    expect(session_login, 200)
    session_headers = {"Authorization": f"Bearer {session_login.get_json()['token']}"}
    expect(client.get("/api/mobile/v1/me", headers=session_headers), 200)

    login = client.post("/api/mobile/v1/login", json={"login_name": "robin", "password": "1234"})
    expect(login, 200)
    token = login.get_json()["token"]
    headers = {"Authorization": f"Bearer {token}"}

    expect(client.get("/api/mobile/v1/me"), 401)
    expect(client.get("/api/mobile/v1/me", headers=headers), 200)
    dashboard = client.get("/api/mobile/v1/dashboard", headers=headers)
    expect(dashboard, 200)
    assert dashboard.get_json()["products"][0]["name"] == "Cola"
    assert dashboard.get_json()["language"] == "en"
    expect(client.get("/api/mobile/v1/statistics", headers=headers), 200)

    booking = client.post("/api/mobile/v1/book", headers=headers, json={"ean": "4000000000001"})
    expect(booking, 200)
    assert booking.get_json()["location_stock"] == 3

    shopping = client.post(
        "/api/mobile/v1/shopping-list",
        headers=headers,
        json={"title": "Mineral water", "quantity": 3},
    )
    expect(shopping, 200)
    item_id = shopping.get_json()["items"][0]["id"]
    expect(client.patch(f"/api/mobile/v1/shopping-list/{item_id}", headers=headers, json={"completed": True}), 200)
    expect(client.delete(f"/api/mobile/v1/shopping-list/{item_id}", headers=headers), 200)
    expect(client.post("/api/mobile/v1/push-device", headers=headers, json={
        "token": "a" * 64,
        "enabled": True,
        "low_stock": True,
        "server_offline": False,
        "backup_failed": True,
        "updates": False,
    }), 200)
    conn = sqlite3.connect(database_file.name)
    push_preferences = conn.execute(
        "SELECT benachrichtigungen_aktiv,niedriger_bestand,server_offline,backup_fehler,updates FROM mobile_push_devices"
    ).fetchone()
    conn.close()
    assert push_preferences == (1, 1, 0, 1, 0)

    expect(client.post("/api/mobile/v1/logout", headers=headers), 200)
    expect(client.get("/api/mobile/v1/me", headers=headers), 401)
    print("All native mobile API integration tests passed.")
finally:
    os.unlink(database_file.name)
