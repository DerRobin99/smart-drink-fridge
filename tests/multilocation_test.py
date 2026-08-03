"""Central scanner API, idempotency and location stock tests."""

import hashlib
import os
import sqlite3
import sys
import tempfile

sys.path.insert(0, "/app")
database_file = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
database_file.close()
os.environ["DATABASE_PATH"] = database_file.name
os.environ["SECRET_KEY"] = "location-test-secret"
os.environ["STORNO_PASSWORT"] = "location-test-password"
os.environ["UPDATE_CHECKER_ENABLED"] = "false"

try:
    from app import app

    conn = sqlite3.connect(database_file.name)
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
    payload = {"event_id": "event-1", "scanner_id": "kitchen-1", "ean": "12345678"}
    assert client.post("/api/scanner/v1/book", json=payload).status_code == 401
    headers = {"Authorization": f"Bearer {token}"}
    response = client.post("/api/scanner/v1/book", json=payload, headers=headers)
    assert response.status_code == 200, response.get_data(as_text=True)
    result = response.get_json()
    assert result["ok"] and result["location"] == "Kitchen"
    duplicate = client.post("/api/scanner/v1/book", json=payload, headers=headers)
    assert duplicate.status_code == 200

    conn = sqlite3.connect(database_file.name)
    assert conn.execute(
        "SELECT bestand FROM standort_bestaende WHERE produkt_id=? AND standort_id=?",
        (product_id, location_id),
    ).fetchone()[0] == 2
    assert conn.execute("SELECT bestand FROM produkte WHERE id=?", (product_id,)).fetchone()[0] == 2
    assert conn.execute("SELECT COUNT(*) FROM buchungen WHERE scanner_id='kitchen-1'").fetchone()[0] == 1
    conn.close()
    print("All multi-location tests passed.")
finally:
    os.unlink(database_file.name)
