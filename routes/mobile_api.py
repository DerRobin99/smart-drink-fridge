"""Authenticated API used by the native Apple clients."""

import hashlib
import secrets
import time
from collections import defaultdict, deque
from datetime import datetime
from functools import wraps

from flask import Blueprint, jsonify, request
from werkzeug.security import check_password_hash

from scanner_booking import book_barcode
from utils.auth import accounts_enabled, current_user
from utils.db import get_db
from version import CURRENT_VERSION


mobile_api_bp = Blueprint("mobile_api", __name__)
_login_attempts = defaultdict(deque)
_LOGIN_WINDOW_SECONDS = 300
_LOGIN_LIMIT = 8


def _token_hash(token):
    return hashlib.sha256(token.encode()).hexdigest()


def _login_allowed(remote_address):
    now = time.monotonic()
    attempts = _login_attempts[remote_address]
    while attempts and now - attempts[0] > _LOGIN_WINDOW_SECONDS:
        attempts.popleft()
    return len(attempts) < _LOGIN_LIMIT


def _record_failed_login(remote_address):
    _login_attempts[remote_address].append(time.monotonic())


def _authenticated_user():
    authorization = request.headers.get("Authorization", "")
    if not authorization.startswith("Bearer "):
        return None
    token = authorization[7:].strip()
    if not token:
        return None
    conn = get_db()
    user = conn.execute(
        """
        SELECT u.id, u.name, u.login_name, u.rolle, t.id AS token_id
        FROM mobile_api_tokens t
        JOIN benutzer u ON u.id=t.benutzer_id
        WHERE t.token_hash=? AND t.widerrufen_am IS NULL AND u.aktiv=1
        """,
        (_token_hash(token),),
    ).fetchone()
    if user:
        conn.execute(
            "UPDATE mobile_api_tokens SET zuletzt_verwendet=? WHERE id=?",
            (datetime.now().strftime("%Y-%m-%d %H:%M:%S"), user["token_id"]),
        )
        conn.commit()
    conn.close()
    return user


def mobile_auth_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        user = _authenticated_user()
        if user is None:
            return jsonify(ok=False, error="unauthorized"), 401
        return view(user, *args, **kwargs)

    return wrapped


def _user_payload(user):
    return {
        "id": user["id"],
        "name": user["name"],
        "login_name": user["login_name"],
        "role": user["rolle"],
    }


def _issue_token(user):
    token = secrets.token_urlsafe(48)
    conn = get_db()
    conn.execute(
        "INSERT INTO mobile_api_tokens (benutzer_id,token_hash) VALUES (?,?)",
        (user["id"], _token_hash(token)),
    )
    conn.commit()
    conn.close()
    return token


@mobile_api_bp.post("/api/mobile/v1/login")
def mobile_login():
    if not accounts_enabled():
        return jsonify(ok=False, error="accounts_disabled"), 409
    remote_address = request.remote_addr or "unknown"
    if not _login_allowed(remote_address):
        return jsonify(ok=False, error="rate_limited"), 429
    data = request.get_json(silent=True) or {}
    login_name = str(data.get("login_name", "")).strip()
    password = str(data.get("password", ""))
    if not login_name or not password or len(login_name) > 120 or len(password) > 512:
        return jsonify(ok=False, error="invalid_request"), 400
    conn = get_db()
    user = conn.execute(
        "SELECT * FROM benutzer WHERE login_name=? COLLATE NOCASE AND aktiv=1",
        (login_name,),
    ).fetchone()
    if user is None or not check_password_hash(user["password_hash"], password):
        conn.close()
        _record_failed_login(remote_address)
        return jsonify(ok=False, error="invalid_credentials"), 401
    conn.close()
    token = _issue_token(user)
    _login_attempts.pop(remote_address, None)
    return jsonify(ok=True, token=token, user=_user_payload(user))


@mobile_api_bp.post("/api/mobile/v1/session")
def mobile_session_login():
    """Exchange an existing authenticated web session for a mobile API token."""
    user = current_user()
    if user is None:
        return jsonify(ok=False, error="unauthorized"), 401
    token = _issue_token(user)
    return jsonify(ok=True, token=token, user=_user_payload(user))


@mobile_api_bp.post("/api/mobile/v1/logout")
@mobile_auth_required
def mobile_logout(user):
    authorization = request.headers.get("Authorization", "")[7:].strip()
    conn = get_db()
    conn.execute(
        "UPDATE mobile_api_tokens SET widerrufen_am=CURRENT_TIMESTAMP WHERE token_hash=?",
        (_token_hash(authorization),),
    )
    conn.commit()
    conn.close()
    return jsonify(ok=True)


@mobile_api_bp.get("/api/mobile/v1/me")
@mobile_auth_required
def mobile_me(user):
    return jsonify(ok=True, user=_user_payload(user), version=CURRENT_VERSION)


@mobile_api_bp.get("/api/mobile/v1/dashboard")
@mobile_auth_required
def mobile_dashboard(user):
    conn = get_db()
    products = conn.execute(
        """
        SELECT p.id,p.name,p.marke,p.verpackungsinfo,p.bestand,p.mindestbestand,
               p.sollbestand,p.preis_cent,p.waehrung,
               GROUP_CONCAT(pb.ean) AS barcodes
        FROM produkte p
        LEFT JOIN produkt_barcodes pb ON pb.produkt_id=p.id
        GROUP BY p.id ORDER BY p.name COLLATE NOCASE
        """
    ).fetchall()
    bookings = conn.execute(
        """
        SELECT id,ean,produkt,aktion,zeitpunkt,menge,bestand_nachher,quelle,
               einzelpreis_cent,waehrung,benutzer_name,standort_name
        FROM buchungen WHERE storniert=0 ORDER BY id DESC LIMIT 30
        """
    ).fetchall()
    summary = conn.execute(
        """
        SELECT COUNT(*) AS products,COALESCE(SUM(bestand),0) AS units,
               COALESCE(SUM(CASE WHEN bestand<=mindestbestand THEN 1 ELSE 0 END),0) AS low_stock
        FROM produkte
        """
    ).fetchone()
    conn.close()
    return jsonify(
        ok=True,
        version=CURRENT_VERSION,
        user=_user_payload(user),
        summary=dict(summary),
        products=[dict(row) for row in products],
        bookings=[dict(row) for row in bookings],
    )


@mobile_api_bp.get("/api/mobile/v1/statistics")
@mobile_auth_required
def mobile_statistics(user):
    conn = get_db()
    totals = conn.execute(
        """
        SELECT COALESCE(-SUM(menge),0) AS drinks,
               COUNT(*) AS bookings,
               COUNT(DISTINCT date(zeitpunkt)) AS active_days
        FROM buchungen
        WHERE benutzer_id=? AND menge<0 AND storniert=0 AND quelle!='storno'
        """,
        (user["id"],),
    ).fetchone()
    by_product = conn.execute(
        """
        SELECT produkt,COALESCE(-SUM(menge),0) AS drinks,
               COALESCE(SUM(-menge*COALESCE(einzelpreis_cent,0)),0) AS cost_cent,
               COALESCE(waehrung,'EUR') AS currency
        FROM buchungen
        WHERE benutzer_id=? AND menge<0 AND storniert=0 AND quelle!='storno'
        GROUP BY produkt,COALESCE(waehrung,'EUR') ORDER BY drinks DESC
        """,
        (user["id"],),
    ).fetchall()
    timeline = conn.execute(
        """
        SELECT date(zeitpunkt) AS day,COALESCE(-SUM(menge),0) AS drinks
        FROM buchungen
        WHERE benutzer_id=? AND menge<0 AND storniert=0 AND quelle!='storno'
          AND zeitpunkt>=datetime('now','localtime','-30 days')
        GROUP BY date(zeitpunkt) ORDER BY day
        """,
        (user["id"],),
    ).fetchall()
    conn.close()
    return jsonify(ok=True, totals=dict(totals), products=[dict(row) for row in by_product], timeline=[dict(row) for row in timeline])


@mobile_api_bp.post("/api/mobile/v1/book")
@mobile_auth_required
def mobile_book(user):
    data = request.get_json(silent=True) or {}
    ean = str(data.get("ean", "")).strip()
    if not ean or len(ean) > 128:
        return jsonify(ok=False, error="invalid_request"), 400
    result = book_barcode(
        ean,
        source="ios-app",
        return_details=True,
        user_id=user["id"],
        user_name=user["name"],
    )
    return jsonify(result), 200 if result.get("ok") else 422


@mobile_api_bp.route("/api/mobile/v1/shopping-list", methods=["GET", "POST"])
@mobile_auth_required
def mobile_shopping_list(user):
    conn = get_db()
    if request.method == "POST":
        data = request.get_json(silent=True) or {}
        title = str(data.get("title", "")).strip()
        try:
            quantity = max(1, min(999, int(data.get("quantity", 1))))
        except (TypeError, ValueError):
            conn.close()
            return jsonify(ok=False, error="invalid_request"), 400
        if not title or len(title) > 200:
            conn.close()
            return jsonify(ok=False, error="invalid_request"), 400
        conn.execute(
            "INSERT INTO mobile_einkaufsliste (titel,menge,erstellt_von) VALUES (?,?,?)",
            (title, quantity, user["id"]),
        )
        conn.commit()
    items = conn.execute(
        "SELECT id,titel,menge,erledigt,erstellt_am,aktualisiert_am FROM mobile_einkaufsliste ORDER BY erledigt,id DESC"
    ).fetchall()
    conn.close()
    return jsonify(ok=True, items=[dict(row) for row in items])


@mobile_api_bp.patch("/api/mobile/v1/shopping-list/<int:item_id>")
@mobile_auth_required
def mobile_shopping_update(user, item_id):
    data = request.get_json(silent=True) or {}
    completed = 1 if data.get("completed") else 0
    conn = get_db()
    cursor = conn.execute(
        "UPDATE mobile_einkaufsliste SET erledigt=?,aktualisiert_am=CURRENT_TIMESTAMP WHERE id=?",
        (completed, item_id),
    )
    conn.commit()
    conn.close()
    return (jsonify(ok=True), 200) if cursor.rowcount else (jsonify(ok=False, error="not_found"), 404)


@mobile_api_bp.delete("/api/mobile/v1/shopping-list/<int:item_id>")
@mobile_auth_required
def mobile_shopping_delete(user, item_id):
    conn = get_db()
    cursor = conn.execute("DELETE FROM mobile_einkaufsliste WHERE id=?", (item_id,))
    conn.commit()
    conn.close()
    return (jsonify(ok=True), 200) if cursor.rowcount else (jsonify(ok=False, error="not_found"), 404)


@mobile_api_bp.post("/api/mobile/v1/push-device")
@mobile_auth_required
def mobile_push_device(user):
    data = request.get_json(silent=True) or {}
    token = str(data.get("token", "")).strip().lower()
    environment = str(data.get("environment", "development")).strip().lower()
    enabled = 1 if data.get("enabled", True) else 0
    low_stock = 1 if data.get("low_stock", True) else 0
    server_offline = 1 if data.get("server_offline", True) else 0
    backup_failed = 1 if data.get("backup_failed", True) else 0
    updates = 1 if data.get("updates", True) else 0
    if environment not in {"development", "production"} or not token or len(token) > 512:
        return jsonify(ok=False, error="invalid_request"), 400
    digest = _token_hash(token)
    conn = get_db()
    conn.execute(
        """
        INSERT INTO mobile_push_devices (
            benutzer_id,device_token_hash,device_token,environment,
            benachrichtigungen_aktiv,niedriger_bestand,server_offline,backup_fehler,updates
        ) VALUES (?,?,?,?,?,?,?,?,?)
        ON CONFLICT(device_token_hash) DO UPDATE SET
            benutzer_id=excluded.benutzer_id,device_token=excluded.device_token,
            environment=excluded.environment,aktiviert=1,
            benachrichtigungen_aktiv=excluded.benachrichtigungen_aktiv,
            niedriger_bestand=excluded.niedriger_bestand,
            server_offline=excluded.server_offline,
            backup_fehler=excluded.backup_fehler,updates=excluded.updates,
            aktualisiert_am=CURRENT_TIMESTAMP
        """,
        (user["id"], digest, token, environment, enabled, low_stock, server_offline, backup_failed, updates),
    )
    conn.commit()
    conn.close()
    return jsonify(ok=True)
