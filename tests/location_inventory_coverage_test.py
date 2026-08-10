"""Complete stock-location helper coverage with an in-memory database."""

import sqlite3
import sys

sys.path.insert(0, "/app")
import location_inventory as inventory

conn = sqlite3.connect(":memory:")
conn.row_factory = sqlite3.Row
conn.executescript("""
CREATE TABLE einstellungen (schluessel TEXT PRIMARY KEY, wert TEXT);
CREATE TABLE standorte (id INTEGER PRIMARY KEY, name TEXT, aktiv INTEGER);
CREATE TABLE scanner_geraete (scanner_id TEXT, name TEXT, standort_id INTEGER, aktiv INTEGER);
CREATE TABLE produkte (id INTEGER PRIMARY KEY, bestand INTEGER, mindestbestand INTEGER, sollbestand INTEGER);
CREATE TABLE standort_bestaende (produkt_id INTEGER, standort_id INTEGER, bestand INTEGER, mindestbestand INTEGER, sollbestand INTEGER, PRIMARY KEY(produkt_id, standort_id));
INSERT INTO einstellungen VALUES ('default_location_id', '1');
INSERT INTO standorte VALUES (1, 'Kitchen', 1), (2, 'Garage', 1);
INSERT INTO scanner_geraete VALUES ('scanner-1', 'Main', 2, 1);
INSERT INTO produkte VALUES (1, 5, 1, 8);
""")

assert inventory.resolve_location(conn, scanner_id="scanner-1")["location_id"] == 2
assert inventory.resolve_location(conn, scanner_id="missing", location_id=2)["location_name"] == "Garage"
assert inventory.resolve_location(conn)["location_id"] == 1

inventory.initialize_product_location(conn, 1, stock=5, minimum=1, target=8)
stock = inventory.location_stock(conn, dict(conn.execute(
    "SELECT id AS produkt_id, bestand, mindestbestand, sollbestand FROM produkte WHERE id=1"
).fetchone()), 1)
assert stock["bestand"] == 5
result = inventory.adjust_location_stock(conn, 1, -2, location_id=1)
assert result["before"] == 5 and result["after"] == 3 and result["total"] == 3

product = dict(conn.execute(
    "SELECT id AS produkt_id, bestand, mindestbestand, sollbestand FROM produkte WHERE id=1"
).fetchone())
assert inventory.location_stock(conn, product, 2)["bestand"] == 0
try:
    inventory.adjust_location_stock(conn, 999, 1, location_id=1)
    raise AssertionError("Unknown product accepted")
except ValueError:
    pass
try:
    inventory.adjust_location_stock(conn, 1, -99, location_id=1)
    raise AssertionError("Negative stock accepted")
except ValueError:
    pass

conn.execute("DELETE FROM einstellungen")
assert inventory.initialize_product_location(conn, 2) == 1
conn.close()
print("All location inventory coverage tests passed.")
