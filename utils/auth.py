import hashlib
import hmac
import os
import secrets
import time
from functools import wraps

from flask import abort, redirect, session

from database import get_setting, set_setting
from utils.db import get_db


RFID_ENROLLMENT_SECONDS = 60


def accounts_enabled():
    return get_setting("benutzerkonten_aktiv", "0").lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def normalize_rfid(value):
    normalized = "".join(
        character
        for character in str(value or "").strip().upper()
        if character.isalnum()
    )
    if len(normalized) < 4 or len(normalized) > 128:
        raise ValueError("invalid RFID value")
    return normalized


def hash_rfid(value):
    normalized = normalize_rfid(value)
    secret = os.environ["SECRET_KEY"].encode()
    return hmac.new(
        secret,
        normalized.encode(),
        hashlib.sha256,
    ).hexdigest()


def start_rfid_enrollment():
    token = secrets.token_urlsafe(24)
    conn = get_db()
    with conn:
        conn.execute(
            """
            INSERT INTO einstellungen (schluessel, wert)
            VALUES ('rfid_anlernen_token', ?)
            ON CONFLICT(schluessel) DO UPDATE SET wert = excluded.wert
            """,
            (token,),
        )
        conn.execute(
            """
            INSERT INTO einstellungen (schluessel, wert)
            VALUES ('rfid_anlernen_bis', ?)
            ON CONFLICT(schluessel) DO UPDATE SET wert = excluded.wert
            """,
            (str(int(time.time()) + RFID_ENROLLMENT_SECONDS),),
        )
        conn.execute(
            """
            INSERT INTO einstellungen (schluessel, wert)
            VALUES ('rfid_anlernen_hash', '')
            ON CONFLICT(schluessel) DO UPDATE SET wert = excluded.wert
            """
        )
    conn.close()
    return token


def capture_rfid_enrollment(uid):
    conn = get_db()
    rows = conn.execute(
        """
        SELECT schluessel, wert FROM einstellungen
        WHERE schluessel IN ('rfid_anlernen_token', 'rfid_anlernen_bis')
        """
    ).fetchall()
    values = {row["schluessel"]: row["wert"] for row in rows}
    try:
        active = (
            bool(values.get("rfid_anlernen_token"))
            and int(values.get("rfid_anlernen_bis", "0")) >= int(time.time())
        )
    except ValueError:
        active = False
    if not active:
        conn.close()
        return False

    digest = hash_rfid(uid)
    with conn:
        conn.execute(
            """
            INSERT INTO einstellungen (schluessel, wert)
            VALUES ('rfid_anlernen_hash', ?)
            ON CONFLICT(schluessel) DO UPDATE SET wert = excluded.wert
            """,
            (digest,),
        )
    conn.close()
    return True


def rfid_enrollment_status(token):
    conn = get_db()
    rows = conn.execute(
        """
        SELECT schluessel, wert FROM einstellungen
        WHERE schluessel IN (
            'rfid_anlernen_token', 'rfid_anlernen_bis', 'rfid_anlernen_hash'
        )
        """
    ).fetchall()
    conn.close()
    values = {row["schluessel"]: row["wert"] for row in rows}
    if not token or not hmac.compare_digest(
        token, values.get("rfid_anlernen_token", "")
    ):
        return "invalid"
    try:
        if int(values.get("rfid_anlernen_bis", "0")) < int(time.time()):
            return "expired"
    except ValueError:
        return "expired"
    return "captured" if values.get("rfid_anlernen_hash") else "waiting"


def consume_rfid_enrollment(token):
    if rfid_enrollment_status(token) != "captured":
        return None
    conn = get_db()
    row = conn.execute(
        "SELECT wert FROM einstellungen WHERE schluessel = 'rfid_anlernen_hash'"
    ).fetchone()
    digest = row["wert"] if row else None
    with conn:
        conn.execute(
            """
            UPDATE einstellungen SET wert = ''
            WHERE schluessel IN (
                'rfid_anlernen_token', 'rfid_anlernen_bis', 'rfid_anlernen_hash'
            )
            """
        )
    conn.close()
    return digest


def current_user():
    user_id = session.get("user_id")
    if not user_id or not accounts_enabled():
        return None

    conn = get_db()
    user = conn.execute(
        """
        SELECT id, name, login_name, rolle, aktiv,
               CASE WHEN rfid_hash IS NULL THEN 0 ELSE 1 END AS has_rfid
        FROM benutzer
        WHERE id = ? AND aktiv = 1
        """,
        (user_id,),
    ).fetchone()
    conn.close()

    if user is None:
        session.clear()
    return user


def set_scanner_user(user_id, duration_seconds=120):
    set_setting("aktiver_scanner_benutzer", user_id)
    set_setting(
        "aktiver_scanner_benutzer_bis",
        int(time.time()) + duration_seconds,
    )


def clear_scanner_user():
    set_setting("aktiver_scanner_benutzer", "")
    set_setting("aktiver_scanner_benutzer_bis", "")


def login_user(user):
    session.clear()
    session["user_id"] = user["id"]
    session.permanent = True
    set_scanner_user(user["id"])


def booking_user():
    user = current_user()
    if user is None:
        return None, None
    return user["id"], user["name"]


def admin_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        user = current_user()
        if user is None:
            return redirect("/anmelden")
        if user["rolle"] != "admin":
            abort(403)
        return view(*args, **kwargs)

    return wrapped
