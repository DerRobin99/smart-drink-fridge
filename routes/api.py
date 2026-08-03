import hashlib
import hmac
import json
import sqlite3
from datetime import datetime

from flask import Blueprint, jsonify, request

from scanner_booking import book_barcode
from utils.db import get_db
from version import CURRENT_VERSION

api_bp = Blueprint("api", __name__)


def _authenticated_scanner(conn):
    authorization = request.headers.get("Authorization", "")
    if not authorization.startswith("Bearer "):
        return None
    supplied = authorization[7:].strip()
    if not supplied:
        return None
    digest = hashlib.sha256(supplied.encode()).hexdigest()
    rows = conn.execute("SELECT * FROM scanner_geraete WHERE aktiv=1").fetchall()
    return next(
        (row for row in rows if hmac.compare_digest(row["api_token_hash"], digest)),
        None,
    )


@api_bp.route("/api/status")
def api_status():
    return {
        "name": "Smart Drink Fridge",
        "version": CURRENT_VERSION,
        "status": "ok",
    }


@api_bp.route("/api/products")
def api_products():
    conn = get_db()

    rows = conn.execute(
        """
        SELECT
            id,
            name,
            marke,
            verpackungsinfo
        FROM produkte
        ORDER BY name
        """
    ).fetchall()

    conn.close()

    return {
        "products": [
            {
                "id": row["id"],
                "name": row["name"],
                "brand": row["marke"],
                "packaging": row["verpackungsinfo"],
            }
            for row in rows
        ]
    }


@api_bp.route("/api/stock")
def api_stock():
    conn = get_db()

    rows = conn.execute(
        """
        SELECT
            id,
            bestand
        FROM produkte
        ORDER BY id
        """
    ).fetchall()

    conn.close()

    return {
        "stock": [
            {
                "product_id": row["id"],
                "stock": row["bestand"],
            }
            for row in rows
        ]
    }


@api_bp.post("/api/scanner/v1/book")
def scanner_api_book():
    conn = get_db()
    scanner = _authenticated_scanner(conn)
    if scanner is None:
        conn.close()
        return jsonify(ok=False, error="unauthorized"), 401
    data = request.get_json(silent=True) or {}
    event_id = str(data.get("event_id", "")).strip()
    scanner_id = str(data.get("scanner_id", "")).strip()
    ean = str(data.get("ean", "")).strip()
    if (
        not event_id
        or len(event_id) > 100
        or scanner_id.casefold() != scanner["scanner_id"].casefold()
        or not ean
    ):
        conn.close()
        return jsonify(ok=False, error="invalid_request"), 400
    cached = conn.execute(
        "SELECT result_json FROM scanner_events WHERE event_id=?", (event_id,)
    ).fetchone()
    if cached:
        conn.close()
        result = json.loads(cached["result_json"])
        return jsonify(result), 409 if result.get("processing") else 200
    try:
        conn.execute(
            "INSERT INTO scanner_events (event_id, scanner_id, result_json) VALUES (?, ?, ?)",
            (event_id, scanner["scanner_id"], json.dumps({"ok": False, "processing": True})),
        )
        conn.execute(
            "UPDATE scanner_geraete SET letzter_kontakt=? WHERE id=?",
            (datetime.now().strftime("%Y-%m-%d %H:%M:%S"), scanner["id"]),
        )
        conn.commit()
    except sqlite3.IntegrityError:
        conn.close()
        return jsonify(ok=False, processing=True), 409
    conn.close()

    try:
        result = book_barcode(
            ean,
            scanner_id=scanner["scanner_id"],
            location_id=scanner["standort_id"],
            source="scanner-api",
            return_details=True,
        )
    except Exception:
        result = {"ok": False, "error": "booking_failed"}
    conn = get_db()
    conn.execute(
        "UPDATE scanner_events SET result_json=? WHERE event_id=?",
        (json.dumps(result, ensure_ascii=False), event_id),
    )
    conn.commit()
    conn.close()
    return jsonify(result), 200 if result.get("ok") else 422


@api_bp.get("/api/scanner/v1/config")
def scanner_api_config():
    conn = get_db()
    scanner = _authenticated_scanner(conn)
    if scanner is None:
        conn.close()
        return jsonify(ok=False, error="unauthorized"), 401
    location = conn.execute(
        "SELECT name FROM standorte WHERE id=?", (scanner["standort_id"],)
    ).fetchone()
    conn.execute(
        "UPDATE scanner_geraete SET letzter_kontakt=? WHERE id=?",
        (datetime.now().strftime("%Y-%m-%d %H:%M:%S"), scanner["id"]),
    )
    conn.commit()
    conn.close()
    return jsonify(
        ok=True,
        scanner_id=scanner["scanner_id"],
        name=scanner["name"],
        location=location["name"],
    )
