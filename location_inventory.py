import os


def resolve_location(conn, scanner_id=None, location_id=None):
    scanner_id = scanner_id or os.environ.get("SCANNER_ID", "").strip()
    if scanner_id:
        scanner = conn.execute(
            """
            SELECT sg.scanner_id, sg.name AS scanner_name, s.id AS location_id,
                   s.name AS location_name
            FROM scanner_geraete sg JOIN standorte s ON s.id=sg.standort_id
            WHERE sg.scanner_id=? COLLATE NOCASE AND sg.aktiv=1 AND s.aktiv=1
            """,
            (scanner_id,),
        ).fetchone()
        if scanner:
            return dict(scanner)
    if location_id:
        location = conn.execute(
            "SELECT id AS location_id, name AS location_name FROM standorte WHERE id=? AND aktiv=1",
            (location_id,),
        ).fetchone()
        if location:
            return {"scanner_id": scanner_id or None, "scanner_name": None, **dict(location)}
    row = conn.execute(
        "SELECT CAST(wert AS INTEGER) FROM einstellungen WHERE schluessel='default_location_id'"
    ).fetchone()
    default_id = row[0] if row else 1
    location = conn.execute(
        "SELECT id AS location_id, name AS location_name FROM standorte WHERE id=?",
        (default_id,),
    ).fetchone()
    if not location:
        location = conn.execute(
            "SELECT id AS location_id, name AS location_name FROM standorte WHERE aktiv=1 ORDER BY id LIMIT 1"
        ).fetchone()
    return {"scanner_id": scanner_id or None, "scanner_name": None, **dict(location)}


def location_stock(conn, product, location_id):
    row = conn.execute(
        "SELECT * FROM standort_bestaende WHERE produkt_id=? AND standort_id=?",
        (product["produkt_id"], location_id),
    ).fetchone()
    if row:
        default_row = conn.execute(
            "SELECT CAST(wert AS INTEGER) FROM einstellungen WHERE schluessel='default_location_id'"
        ).fetchone()
        if location_id == (default_row[0] if default_row else 1):
            distributed = conn.execute(
                "SELECT COALESCE(SUM(bestand),0) FROM standort_bestaende WHERE produkt_id=?",
                (product["produkt_id"],),
            ).fetchone()[0]
            delta = product["bestand"] - distributed
            if delta and row["bestand"] + delta >= 0:
                conn.execute(
                    "UPDATE standort_bestaende SET bestand=bestand+? WHERE produkt_id=? AND standort_id=?",
                    (delta, product["produkt_id"], location_id),
                )
                row = conn.execute(
                    "SELECT * FROM standort_bestaende WHERE produkt_id=? AND standort_id=?",
                    (product["produkt_id"], location_id),
                ).fetchone()
        return row
    default_row = conn.execute(
        "SELECT CAST(wert AS INTEGER) FROM einstellungen WHERE schluessel='default_location_id'"
    ).fetchone()
    initial = product["bestand"] if location_id == (default_row[0] if default_row else 1) else 0
    conn.execute(
        "INSERT INTO standort_bestaende (produkt_id, standort_id, bestand, mindestbestand, sollbestand) VALUES (?, ?, ?, ?, ?)",
        (product["produkt_id"], location_id, initial, product["mindestbestand"], product["sollbestand"]),
    )
    return conn.execute(
        "SELECT * FROM standort_bestaende WHERE produkt_id=? AND standort_id=?",
        (product["produkt_id"], location_id),
    ).fetchone()


def recalculate_product_stock(conn, product_id):
    total = conn.execute(
        "SELECT COALESCE(SUM(bestand),0) FROM standort_bestaende WHERE produkt_id=?",
        (product_id,),
    ).fetchone()[0]
    conn.execute("UPDATE produkte SET bestand=? WHERE id=?", (total, product_id))
    return total


def adjust_location_stock(conn, product_id, delta, location_id=None):
    location = resolve_location(conn, location_id=location_id)
    product = conn.execute(
        "SELECT id AS produkt_id, bestand, mindestbestand, sollbestand FROM produkte WHERE id=?",
        (product_id,),
    ).fetchone()
    if not product:
        raise ValueError("unknown product")
    stock = location_stock(conn, product, location["location_id"])
    before = stock["bestand"]
    after = before + delta
    if after < 0:
        raise ValueError("insufficient location stock")
    conn.execute(
        "UPDATE standort_bestaende SET bestand=? WHERE produkt_id=? AND standort_id=?",
        (after, product_id, location["location_id"]),
    )
    total = recalculate_product_stock(conn, product_id)
    return {**location, "before": before, "after": after, "total": total}


def initialize_product_location(conn, product_id, stock=0, minimum=0, target=0):
    row = conn.execute(
        "SELECT CAST(wert AS INTEGER) FROM einstellungen WHERE schluessel='default_location_id'"
    ).fetchone()
    location_id = row[0] if row else 1
    conn.execute(
        "INSERT OR REPLACE INTO standort_bestaende (produkt_id, standort_id, bestand, mindestbestand, sollbestand) VALUES (?, ?, ?, ?, ?)",
        (product_id, location_id, stock, minimum, target),
    )
    return location_id
