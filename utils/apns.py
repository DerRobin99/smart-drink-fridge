"""Token-based Apple Push Notification delivery for registered iOS devices."""

import base64
import json
import os
import time

import httpx
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec

from utils.db import get_db


PREFERENCE_COLUMNS = {
    "low_stock": "niedriger_bestand",
    "server_offline": "server_offline",
    "backup_failed": "backup_fehler",
    "updates": "updates",
}
_jwt_cache = {"token": "", "created": 0}


def _b64url(value):
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def configured():
    path = os.environ.get("APNS_PRIVATE_KEY_PATH", "").strip()
    return bool(
        os.environ.get("APNS_KEY_ID", "").strip()
        and os.environ.get("APNS_TEAM_ID", "").strip()
        and path
        and os.path.isfile(path)
    )


def _provider_token():
    now = int(time.time())
    if _jwt_cache["token"] and now - _jwt_cache["created"] < 50 * 60:
        return _jwt_cache["token"]
    header = _b64url(json.dumps({"alg": "ES256", "kid": os.environ["APNS_KEY_ID"]}, separators=(",", ":")).encode())
    claims = _b64url(json.dumps({"iss": os.environ["APNS_TEAM_ID"], "iat": now}, separators=(",", ":")).encode())
    signing_input = f"{header}.{claims}".encode("ascii")
    with open(os.environ["APNS_PRIVATE_KEY_PATH"], "rb") as handle:
        key = serialization.load_pem_private_key(handle.read(), password=None)
    der = key.sign(signing_input, ec.ECDSA(hashes.SHA256()))
    r, s = __import__("cryptography.hazmat.primitives.asymmetric.utils", fromlist=["decode_dss_signature"]).decode_dss_signature(der)
    signature = _b64url(r.to_bytes(32, "big") + s.to_bytes(32, "big"))
    _jwt_cache.update(token=f"{header}.{claims}.{signature}", created=now)
    return _jwt_cache["token"]


def send_mobile_push(event, title, message, user_id=None):
    preference = PREFERENCE_COLUMNS.get(event)
    if not preference:
        return {"sent": 0, "failed": 0, "reason": "unknown_event"}
    if not configured():
        return {"sent": 0, "failed": 0, "reason": "not_configured"}

    conn = get_db()
    try:
        where = f"aktiviert=1 AND benachrichtigungen_aktiv=1 AND {preference}=1"
        params = []
        if user_id is not None:
            where += " AND benutzer_id=?"
            params.append(user_id)
        devices = conn.execute(
            f"SELECT id,device_token,environment FROM mobile_push_devices WHERE {where}",
            params,
        ).fetchall()
        bundle_id = os.environ.get("APNS_BUNDLE_ID", "de.derrobin99.smartdrinkfridge").strip()
        payload = {"aps": {"alert": {"title": str(title)[:120], "body": str(message)[:1000]}, "sound": "default"}, "event": event}
        headers = {"authorization": f"bearer {_provider_token()}", "apns-topic": bundle_id, "apns-push-type": "alert", "apns-priority": "10"}
        sent = failed = 0
        with httpx.Client(http2=True, timeout=10) as client:
            for device in devices:
                host = "api.sandbox.push.apple.com" if device["environment"] == "development" else "api.push.apple.com"
                try:
                    response = client.post(f"https://{host}/3/device/{device['device_token']}", headers=headers, json=payload)
                except httpx.HTTPError:
                    failed += 1
                    continue
                if response.status_code == 200:
                    sent += 1
                else:
                    failed += 1
                    try:
                        reason = response.json().get("reason", "")
                    except (ValueError, AttributeError):
                        reason = ""
                    if response.status_code in {400, 410} and reason in {"BadDeviceToken", "DeviceTokenNotForTopic", "Unregistered"}:
                        conn.execute("UPDATE mobile_push_devices SET aktiviert=0 WHERE id=?", (device["id"],))
        conn.commit()
        return {"sent": sent, "failed": failed, "reason": "sent" if sent else "no_recipients"}
    finally:
        conn.close()
