"""Integration tests for the public web, inventory, and product routes."""

import os
import sqlite3
import sys
import tempfile

sys.path.insert(0, "/app")

database_file = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
database_file.close()
os.environ["DATABASE_PATH"] = database_file.name
os.environ["SECRET_KEY"] = "ci-route-test-secret"
os.environ["STORNO_PASSWORT"] = "ci-storno"
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

    for path in ("/", "/barcode", "/statistik", "/api/status", "/api/products", "/api/stock"):
        expect(client.get(path), 200)

    expect(client.get("/service-worker.js"), 200)
    expect(client.get("/api/produkt-suche/not-an-ean"), 400)
    expect(client.get("/produkt/99999"), 404)

    # Input validation for barcode creation.
    expect(client.post("/barcode/speichern", data={"ean": ""}), 400)
    expect(client.post("/barcode/speichern", data={"ean": "123", "aktion": "invalid"}), 400)
    expect(client.post("/barcode/speichern", data={"ean": "123", "modus": "invalid"}), 400)
    expect(
        client.post(
            "/barcode/speichern",
            data={
                "ean": "4000000000001",
                "modus": "neu",
                "aktion": "entnehmen",
                "menge": "1",
                "name": "Integration Cola",
                "marke": "Test Brand",
                "verpackungsinfo": "500 ml",
                "bestand": "5",
                "mindestbestand": "2",
                "sollbestand": "8",
                "preis": "1.50",
                "waehrung": "USD",
            },
        ),
        302,
    )

    conn = sqlite3.connect(database_file.name)
    conn.row_factory = sqlite3.Row
    product = conn.execute(
        "SELECT * FROM produkte WHERE name = 'Integration Cola'"
    ).fetchone()
    assert product is not None
    assert product["waehrung"] == "EUR"
    assert 'name="waehrung"' not in client.get("/barcode").get_data(as_text=True)
    product_id = product["id"]
    conn.close()

    products = client.get("/api/products").get_json()["products"]
    stock = client.get("/api/stock").get_json()["stock"]
    assert any(row["id"] == product_id for row in products)
    assert any(row["product_id"] == product_id and row["stock"] == 5 for row in stock)

    for period in ("7", "30", "3m", "6m", "1j", "alle", "invalid"):
        expect(client.get(f"/produkt/{product_id}?zeitraum={period}"), 200)
        expect(client.get(f"/statistik?zeitraum={period}"), 200)

    response = client.post(f"/bestand/{product_id}/plus", data={"next": "/"})
    expect(response, 302)
    assert response.headers["Location"] == "/"
    response = client.post(
        f"/bestand/{product_id}/minus",
        data={"next": f"/produkt/{product_id}"},
    )
    expect(response, 302)
    assert response.headers["Location"] == f"/produkt/{product_id}"
    expect(client.post(f"/bestand/{product_id}/invalid"), 302)
    expect(client.post(f"/bestand/{product_id}/einlagern", data={"menge": "bad"}), 302)
    expect(client.post(f"/bestand/{product_id}/einlagern", data={"menge": "0"}), 302)
    expect(
        client.post(
            f"/bestand/{product_id}/einlagern",
            data={"menge": "2", "preis": "2.00", "waehrung": "USD"},
        ),
        400,
    )
    expect(
        client.post(
            f"/bestand/{product_id}/einlagern",
            data={"menge": "2", "preis": "2.00", "waehrung": "EUR"},
        ),
        302,
    )

    expect(
        client.post(
            f"/produkt/{product_id}/bearbeiten",
            data={
                "name": "Integration Cola Zero",
                "marke": "Test Brand",
                "verpackungsinfo": "500 ml",
                "bestand": "7",
                "mindestbestand": "3",
                "sollbestand": "2",
            },
        ),
        302,
    )
    expect(client.post(f"/produkt/{product_id}/bearbeiten", data={"name": ""}), 302)

    # Add and edit a second barcode for the existing product.
    expect(
        client.post(
            "/barcode/speichern",
            data={
                "ean": "4000000000002",
                "modus": "bestehend",
                "produkt_id": str(product_id),
                "aktion": "einlagern",
                "menge": "6",
            },
        ),
        302,
    )
    expect(
        client.post(
            "/barcode/4000000000002/bearbeiten",
            data={"produkt_id": str(product_id), "aktion": "entnehmen", "menge": "2"},
        ),
        302,
    )
    expect(client.post("/barcode/missing/bearbeiten", data={"produkt_id": product_id}), 404)
    expect(client.post(f"/produkt/{product_id}/barcode/4000000000002/loeschen"), 302)

    # A scanner booking exercises all undo validation and success paths.
    conn = sqlite3.connect(database_file.name)
    cursor = conn.execute(
        """
        INSERT INTO buchungen (
            ean, produkt, aktion, menge, bestand_vorher, bestand_nachher,
            quelle, einzelpreis_cent, waehrung
        ) VALUES (?, ?, 'Ausgebucht', -1, 8, 7, 'scanner', 150, 'EUR')
        """,
        ("4000000000001", "Integration Cola Zero"),
    )
    booking_id = cursor.lastrowid
    conn.commit()
    conn.close()
    expect(client.post(f"/buchung/{booking_id}/stornieren", data={"passwort": "wrong"}), 403)
    expect(client.post("/buchung/99999/stornieren", data={"passwort": "ci-storno"}), 404)
    expect(client.post(f"/buchung/{booking_id}/stornieren", data={"passwort": "ci-storno"}), 302)
    expect(client.post(f"/buchung/{booking_id}/stornieren", data={"passwort": "ci-storno"}), 302)

    # Settings and language behavior stay usable without optional accounts.
    expect(client.get("/einstellungen"), 200)
    expect(
        client.post(
            "/einstellungen",
            data={"show_empty_products": "on", "theme_accent": "invalid"},
        ),
        302,
    )
    for language in ("de", "en", "fr", "invalid"):
        expect(client.get(f"/sprache/{language}"), 302)

    # Deletion is protected while stock exists, then succeeds at zero stock.
    expect(client.post(f"/produkt/{product_id}/loeschen"), 302)
    conn = sqlite3.connect(database_file.name)
    conn.execute("UPDATE produkte SET bestand = 0 WHERE id = ?", (product_id,))
    conn.commit()
    conn.close()
    expect(client.post(f"/produkt/{product_id}/loeschen"), 302)
    expect(client.get(f"/produkt/{product_id}"), 404)

    print("All route and inventory integration tests passed.")
finally:
    os.unlink(database_file.name)
