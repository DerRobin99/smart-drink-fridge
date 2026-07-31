"""Tests for update, logo, product merge/search, and RFID helper branches."""

import os
import sqlite3
import sys
import tempfile
import time
from unittest.mock import Mock

sys.path.insert(0, "/app")
db_file = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
db_file.close()
os.environ["DATABASE_PATH"] = db_file.name
os.environ["SECRET_KEY"] = "ci-remaining-secret"
os.environ["UPDATE_CHECKER_ENABLED"] = "true"

try:
    import app as app_module
    import routes.products as products_module
    from utils import auth

    app_module.app.config.update(TESTING=True)
    client = app_module.app.test_client()

    assert app_module.version_tuple("v1.2.3") == (1, 2, 3)
    assert app_module.version_tuple("broken") == (0,)
    release = Mock()
    release.raise_for_status.return_value = None
    release.json.return_value = {"tag_name": "v99.0.0", "html_url": "https://example.test/release"}
    app_module.requests.get = Mock(return_value=release)
    app_module._update_cache["checked_at"] = None
    assert app_module.get_update_info(force=True)["update_available"]
    assert app_module.get_update_info()["latest_version"] == "v99.0.0"
    release.json.return_value = {}
    assert app_module.get_update_info(force=True)["error"]
    app_module.requests.get = Mock(side_effect=app_module.requests.RequestException("offline"))
    assert app_module.get_update_info(force=True)["error"]

    assert app_module.get_brand_logo("") is None
    search = Mock()
    search.raise_for_status.return_value = None
    search.json.return_value = {"search": [{"id": "Q1", "label": "Test Brand", "description": "beverage brand"}]}
    entity = Mock()
    entity.raise_for_status.return_value = None
    entity.json.return_value = {"entities": {"Q1": {"claims": {"P154": [{"mainsnak": {"datavalue": {"value": "Logo.svg"}}}]}}}}
    commons = Mock()
    commons.raise_for_status.return_value = None
    commons.json.return_value = {"query": {"pages": {"1": {"imageinfo": [{"thumburl": "https://img.test/logo.png"}]}}}}
    app_module.requests.get = Mock(side_effect=[search, entity, commons])
    assert app_module.get_brand_logo("Test Brand") == "https://img.test/logo.png"
    assert app_module.get_brand_logo("Test Brand") == "https://img.test/logo.png"
    assert app_module.inject_brand_logo_helper()["brand_logo"] is app_module.get_brand_logo

    conn = sqlite3.connect(db_file.name)
    conn.execute("INSERT INTO buchungen (ean, produkt, aktion, menge) VALUES ('sum', 'X', 'x', -2)")
    conn.commit()
    conn.row_factory = sqlite3.Row
    assert app_module.verbrauch(conn, "sum") == 2
    assert app_module.verbrauch(conn, "sum", "-7 days") == 2
    conn.close()

    # Product creation validation and OpenFoodFacts outcomes.
    assert client.post("/produkt", data={"ean": "1", "name": "X", "bestand": "1", "preis": "bad", "waehrung": "EUR"}).status_code == 400
    assert client.post("/produkt", data={"ean": "legacy", "name": "Legacy", "bestand": "2", "preis": "1.00", "waehrung": "EUR"}).status_code == 302
    off = Mock()
    off.raise_for_status.return_value = None
    off.json.return_value = {"status": 0}
    products_module.requests.get = Mock(return_value=off)
    assert client.get("/api/produkt-suche/12345").get_json()["gefunden"] is False
    off.json.return_value = {"status": 1, "product": {"product_name_de": "Cola", "brands": "Brand", "quantity": "500 ml"}}
    assert client.get("/api/produkt-suche/12345").get_json()["name"] == "Cola"
    products_module.requests.get = Mock(side_effect=products_module.requests.RequestException("offline"))
    assert client.get("/api/produkt-suche/12345").status_code == 502

    conn = sqlite3.connect(db_file.name)
    conn.execute("INSERT INTO produkte (id,name,bestand,preis_cent,waehrung) VALUES (10,'Source',2,100,'EUR'),(11,'Target',3,200,'USD'),(12,'Empty',0,0,'EUR')")
    conn.execute("INSERT INTO produkt_barcodes (ean,produkt_id,menge,aktion) VALUES ('merge-code',10,1,'entnehmen')")
    conn.commit()
    conn.close()
    assert client.post("/produkt/10/zusammenfuehren", data={"ziel_id": "bad"}).status_code == 400
    assert client.post("/produkt/10/zusammenfuehren", data={"ziel_id": "10"}).status_code == 400
    assert client.post("/produkt/999/zusammenfuehren", data={"ziel_id": "11"}).status_code == 404
    assert client.post("/produkt/10/zusammenfuehren", data={"ziel_id": "11"}).status_code == 400
    assert client.post("/produkt/10/zusammenfuehren", data={"ziel_id": "12"}).status_code == 302

    # Full RFID enrollment state machine and scanner-user helpers.
    token = auth.start_rfid_enrollment()
    assert auth.rfid_enrollment_status("wrong") == "invalid"
    assert auth.rfid_enrollment_status(token) == "waiting"
    assert auth.capture_rfid_enrollment("A1B2C3D4")
    assert auth.rfid_enrollment_status(token) == "captured"
    assert auth.consume_rfid_enrollment(token)
    assert auth.consume_rfid_enrollment(token) is None
    try:
        auth.normalize_rfid("x")
    except ValueError:
        pass
    else:
        raise AssertionError("Short RFID accepted")

    print("All remaining logic tests passed.")
finally:
    os.unlink(db_file.name)
