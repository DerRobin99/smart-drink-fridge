"""Central scanner API, idempotency and location stock tests."""

import hashlib
import os
import sqlite3
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, "/app")
database_file = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
database_file.close()
os.environ["DATABASE_PATH"] = database_file.name
os.environ["SECRET_KEY"] = "location-test-secret"
os.environ["STORNO_PASSWORT"] = "location-test-password"
os.environ["UPDATE_CHECKER_ENABLED"] = "false"
scanner_directory = tempfile.TemporaryDirectory()
os.environ["SCANNER_DATA_DIR"] = scanner_directory.name

try:
    from app import app
    app.config.update(TESTING=True)

    conn = sqlite3.connect(database_file.name)
    conn.execute(
        "INSERT INTO benutzer (id,name,login_name,password_hash,rolle,aktiv) VALUES (99,'Admin','admin','x','admin',1)"
    )
    conn.execute("UPDATE einstellungen SET wert='1' WHERE schluessel='benutzerkonten_aktiv'")
    conn.execute("INSERT INTO standorte (name) VALUES ('Kitchen')")
    location_id = conn.execute("SELECT id FROM standorte WHERE name='Kitchen'").fetchone()[0]
    token = "test-scanner-token"
    conn.execute(
        "INSERT INTO scanner_geraete (scanner_id,name,standort_id,api_token_hash) VALUES (?,?,?,?)",
        ("kitchen-1", "Kitchen scanner", location_id, hashlib.sha256(token.encode()).hexdigest()),
    )
    product_id = conn.execute(
        "INSERT INTO produkte (name,marke,verpackungsinfo,bestand,mindestbestand,sollbestand) VALUES ('Cola','','',3,0,6)"
    ).lastrowid
    conn.execute("INSERT INTO produkt_barcodes (produkt_id,ean) VALUES (?,?)", (product_id, "12345678"))
    conn.execute(
        "INSERT INTO standort_bestaende (produkt_id,standort_id,bestand,mindestbestand,sollbestand) VALUES (?,?,?,?,?)",
        (product_id, location_id, 3, 0, 6),
    )
    conn.commit()
    conn.close()

    client = app.test_client()
    with client.session_transaction() as session:
        session["user_id"] = 99

    # Full location/scanner administration workflow.
    from scanner_diagnostics import publish_local_scanner
    publish_local_scanner("local-auto", "Automatically found scanner")
    locations_page = client.get("/einstellungen/standorte")
    assert locations_page.status_code == 200, (locations_page.status_code, locations_page.headers.get("Location"), locations_page.get_data(as_text=True)[:500])
    conn = sqlite3.connect(database_file.name)
    local_scanner = conn.execute(
        "SELECT id,name,lokal_erkannt FROM scanner_geraete WHERE scanner_id='local-auto'"
    ).fetchone()
    assert local_scanner[1:] == ("Automatically found scanner", 1)
    conn.close()
    assert client.post("/einstellungen/standorte/anlegen", data={"name": ""}).status_code == 400
    assert client.post("/einstellungen/standorte/anlegen", data={"name": "Garage"}).status_code == 302
    assert client.post("/einstellungen/standorte/anlegen", data={"name": "Garage"}).status_code == 409
    conn = sqlite3.connect(database_file.name)
    garage_id = conn.execute("SELECT id FROM standorte WHERE name='Garage'").fetchone()[0]
    conn.close()
    assert client.post(
        f"/einstellungen/scanner/{local_scanner[0]}/bearbeiten",
        data={"name": "Edited local scanner", "location_id": garage_id, "active": "1"},
    ).status_code == 302
    assert client.get("/einstellungen/standorte").status_code == 200
    conn = sqlite3.connect(database_file.name)
    assert conn.execute(
        "SELECT name,standort_id FROM scanner_geraete WHERE id=?", (local_scanner[0],)
    ).fetchone() == ("Edited local scanner", garage_id)
    conn.close()
    assert client.post(
        "/einstellungen/scanner/99999/bearbeiten",
        data={"name": "Missing", "location_id": garage_id, "active": "1"},
    ).status_code == 404
    # A LAN scanner may discover the server, but remains blocked until approved.
    pairing_secret = "pairing-secret-with-at-least-thirty-two-characters"
    pairing_data = {
        "scanner_id": "cellar-network",
        "name": "Cellar network scanner",
        "pairing_secret": pairing_secret,
    }
    assert client.post("/api/scanner/v1/pair", json=pairing_data).get_json()["status"] == "pending"
    assert client.post("/api/scanner/v1/pair/status", json=pairing_data).get_json()["status"] == "pending"
    assert client.post(
        "/einstellungen/scanner/kopplung/cellar-network/bestaetigen",
        data={"location_id": garage_id},
    ).status_code == 302
    approved = client.post("/api/scanner/v1/pair/status", json=pairing_data).get_json()
    assert approved["status"] == "approved" and approved["token"]
    assert client.get(
        "/api/scanner/v1/config",
        headers={"Authorization": f"Bearer {approved['token']}"},
    ).get_json()["location"] == "Garage"
    conflicting = dict(pairing_data, pairing_secret="different-secret-with-at-least-thirty-two-characters")
    assert client.post("/api/scanner/v1/pair", json=conflicting).status_code == 409
    assert client.post("/einstellungen/standorte/config", data={"default_location_id": garage_id, "shopping_list_scope": "bad"}).status_code == 400
    assert client.post("/einstellungen/standorte/config", data={"default_location_id": 9999, "shopping_list_scope": "shared"}).status_code == 400
    assert client.post("/einstellungen/standorte/config", data={"default_location_id": garage_id, "shopping_list_scope": "separate"}).status_code == 302
    assert client.post("/einstellungen/scanner/anlegen", data={"name": "X", "scanner_id": "!", "location_id": garage_id}).status_code == 400
    scanner_response = client.post("/einstellungen/scanner/anlegen", data={"name": "Garage scanner", "scanner_id": "garage-1", "location_id": garage_id})
    assert scanner_response.status_code == 200 and "Scanner-Token" in scanner_response.get_data(as_text=True)
    assert client.post("/einstellungen/scanner/anlegen", data={"name": "Garage scanner", "scanner_id": "garage-1", "location_id": garage_id}).status_code == 409
    assert client.post("/einstellungen/standorte/bestand", data={"product_id": product_id, "location_id": location_id, "stock": 4, "minimum": 1, "target": 8}).status_code == 302
    assert client.post("/einstellungen/standorte/umlagern", data={"product_id": product_id, "from_location_id": location_id, "to_location_id": location_id, "quantity": 1}).status_code == 400
    assert client.post("/einstellungen/standorte/umlagern", data={"product_id": product_id, "from_location_id": location_id, "to_location_id": garage_id, "quantity": 99}).status_code == 409
    assert client.post("/einstellungen/standorte/umlagern", data={"product_id": product_id, "from_location_id": location_id, "to_location_id": garage_id, "quantity": 1}).status_code == 302

    payload = {"event_id": "event-1", "scanner_id": "kitchen-1", "ean": "12345678"}
    assert client.post("/api/scanner/v1/book", json=payload).status_code == 401
    headers = {"Authorization": f"Bearer {token}"}
    response = client.post("/api/scanner/v1/book", json=payload, headers=headers)
    assert response.status_code == 200, response.get_data(as_text=True)
    result = response.get_json()
    assert result["ok"] and result["location"] == "Kitchen"
    duplicate = client.post("/api/scanner/v1/book", json=payload, headers=headers)
    assert duplicate.status_code == 200
    config = client.get("/api/scanner/v1/config", headers=headers)
    assert config.status_code == 200 and config.get_json()["location"] == "Kitchen"

    # Scanner diagnostics page, lookup, status and sound command channel.
    assert client.get("/einstellungen/scanner-diagnose").status_code == 200
    assert client.get("/api/scanner-diagnostics").status_code == 200
    assert client.get("/einstellungen/scanner-diagnose/frame.jpg").status_code == 404
    assert client.post("/einstellungen/scanner-diagnose/testscan", data={"ean": "12345678"}).get_json()["ok"]
    assert not client.post("/einstellungen/scanner-diagnose/testscan", data={"ean": "missing"}).get_json()["ok"]
    assert client.post("/einstellungen/scanner-diagnose/ton", data={"pattern": "success", "volume": "75"}).status_code == 302
    assert client.post("/einstellungen/scanner-diagnose/ton", data={"pattern": "invalid", "volume": "75"}).status_code == 400

    # Remote scanner queues during an outage and flushes exactly once later.
    import scanner_client
    os.environ.update({"SCANNER_SERVER_URL": "https://central.example", "SCANNER_ID": "remote-1", "SCANNER_TOKEN": "secret"})

    def offline(*args, **kwargs):
        raise scanner_client.requests.RequestException("offline")

    scanner_client.requests.post = offline
    queued = scanner_client.remote_book_barcode("998877")
    assert queued["queued"] and scanner_client.queue_path().is_file()

    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {"ok": True}

    scanner_client.requests.post = lambda *args, **kwargs: Response()
    assert scanner_client.flush_queue() == [{"ok": True}]
    assert not scanner_client.queue_path().exists()
    assert scanner_client.remote_book_barcode("112233")["ok"]

    conn = sqlite3.connect(database_file.name)
    assert conn.execute(
        "SELECT bestand FROM standort_bestaende WHERE produkt_id=? AND standort_id=?",
        (product_id, location_id),
    ).fetchone()[0] == 2
    assert conn.execute("SELECT bestand FROM produkte WHERE id=?", (product_id,)).fetchone()[0] == 3
    assert conn.execute("SELECT COUNT(*) FROM buchungen WHERE scanner_id='kitchen-1'").fetchone()[0] == 1
    conn.close()
    print("All multi-location tests passed.")
finally:
    scanner_directory.cleanup()
    os.unlink(database_file.name)
