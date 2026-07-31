"""Validation and failure-path integration tests."""

import os
import sqlite3
import sys
import tempfile

sys.path.insert(0, "/app")
db_file = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
db_file.close()
os.environ["DATABASE_PATH"] = db_file.name
os.environ["SECRET_KEY"] = "ci-errors-secret"
os.environ["STORNO_PASSWORT"] = "undo"
os.environ["UPDATE_CHECKER_ENABLED"] = "false"

try:
    from app import app

    app.config.update(TESTING=True)
    client = app.test_client()
    create = {
        "ean": "11111111", "modus": "neu", "aktion": "entnehmen", "menge": "1",
        "name": "Branch Drink", "bestand": "0", "mindestbestand": "1", "sollbestand": "3",
        "preis": "1.00", "waehrung": "EUR",
    }
    assert client.post("/barcode/speichern", data=create).status_code == 302
    assert client.post("/barcode/speichern", data=create).status_code == 400
    assert client.post("/barcode/speichern", data={**create, "ean": "222", "name": ""}).status_code == 400
    assert client.post("/barcode/speichern", data={"ean": "222", "modus": "bestehend", "produkt_id": "bad"}).status_code == 400
    assert client.post("/barcode/speichern", data={"ean": "222", "modus": "bestehend", "produkt_id": "999"}).status_code == 404

    conn = sqlite3.connect(db_file.name)
    product_id = conn.execute("SELECT id FROM produkte WHERE name='Branch Drink'").fetchone()[0]
    conn.close()
    assert client.post("/barcode/11111111/bearbeiten", data={"produkt_id": product_id, "menge": "0"}).status_code == 400
    assert client.post("/barcode/11111111/bearbeiten", data={"produkt_id": product_id, "aktion": "bad"}).status_code == 400
    assert client.post("/barcode/11111111/bearbeiten", data={"produkt_id": 999}).status_code == 404
    assert client.post("/barcode/missing/bearbeiten", data={"produkt_id": product_id}).status_code == 404

    assert client.post("/bestand/999/plus").status_code == 302
    assert client.post(f"/bestand/{product_id}/minus").status_code == 302
    assert client.post("/bestand/999/einlagern", data={"menge": "2", "waehrung": "EUR"}).status_code == 302
    assert client.post(f"/bestand/{product_id}/einlagern", data={"menge": "2", "preis": "bad", "waehrung": "EUR"}).status_code == 400

    conn = sqlite3.connect(db_file.name)
    web_id = conn.execute("INSERT INTO buchungen (ean,produkt,aktion,menge,quelle) VALUES ('11111111','Branch Drink','Web',-1,'web')").lastrowid
    missing_code_id = conn.execute("INSERT INTO buchungen (ean,produkt,aktion,menge,quelle) VALUES ('missing','Branch Drink','Scan',-1,'scanner')").lastrowid
    conn.commit()
    conn.close()
    assert client.post(f"/buchung/{web_id}/stornieren", data={"passwort": "undo"}).status_code == 400
    assert client.post(f"/buchung/{missing_code_id}/stornieren", data={"passwort": "undo"}).status_code == 404

    # Login throttling and invalid account-assignment branches.
    conn = sqlite3.connect(db_file.name)
    conn.execute("UPDATE einstellungen SET wert='1' WHERE schluessel='benutzerkonten_aktiv'")
    conn.commit()
    conn.close()
    for _ in range(11):
        assert client.post("/anmelden", data={"login_name": "none", "password": "bad"}).status_code == 302
    assert client.get("/").status_code == 302

    print("All error branch tests passed.")
finally:
    os.unlink(db_file.name)
