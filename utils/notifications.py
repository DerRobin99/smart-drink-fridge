import base64
import hashlib
import os

import requests
from cryptography.fernet import Fernet, InvalidToken

from database import get_setting, set_setting


PUSHOVER_API_URL = "https://api.pushover.net/1/messages.json"
PUSHOVER_EVENTS = {
    "low_stock": "pushover_event_low_stock",
    "out_of_stock": "pushover_event_out_of_stock",
    "removed": "pushover_event_removed",
    "restocked": "pushover_event_restocked",
    "unknown_barcode": "pushover_event_unknown_barcode",
    "scan_blocked": "pushover_event_scan_blocked",
}


def _fernet():
    secret = os.environ["SECRET_KEY"].encode("utf-8")
    key = base64.urlsafe_b64encode(hashlib.sha256(secret).digest())
    return Fernet(key)


def encrypt_secret(value):
    return _fernet().encrypt(value.encode("utf-8")).decode("ascii")


def decrypt_secret(value):
    if not value:
        return ""
    try:
        return _fernet().decrypt(value.encode("ascii")).decode("utf-8")
    except (InvalidToken, ValueError, UnicodeError):
        return ""


def save_pushover_credentials(user_key=None, app_token=None, clear=False):
    if clear:
        set_setting("pushover_user_encrypted", "")
        set_setting("pushover_token_encrypted", "")
        set_setting("pushover_env_fallback_disabled", "1")
        return
    if user_key:
        set_setting("pushover_user_encrypted", encrypt_secret(user_key))
    if app_token:
        set_setting("pushover_token_encrypted", encrypt_secret(app_token))


def get_pushover_credentials():
    encrypted_user = get_setting("pushover_user_encrypted", "")
    encrypted_token = get_setting("pushover_token_encrypted", "")
    user_key = decrypt_secret(encrypted_user)
    app_token = decrypt_secret(encrypted_token)
    if user_key and app_token:
        return user_key, app_token, "database"

    env_disabled = get_setting(
        "pushover_env_fallback_disabled", "0"
    ).lower() in {"1", "true", "yes", "on"}
    if not env_disabled:
        env_user = os.environ.get("PUSHOVER_USER", "").strip()
        env_token = os.environ.get("PUSHOVER_TOKEN", "").strip()
        if env_user and env_token:
            return env_user, env_token, "environment"
    return "", "", ""


def pushover_configured():
    user_key, app_token, source = get_pushover_credentials()
    return bool(user_key and app_token), source


def notification_enabled(event):
    if event not in PUSHOVER_EVENTS:
        return False
    enabled = get_setting("pushover_enabled", "0").lower() in {
        "1", "true", "yes", "on"
    }
    selected = get_setting(PUSHOVER_EVENTS[event], "0").lower() in {
        "1", "true", "yes", "on"
    }
    return enabled and selected


def send_pushover(event, title, message, force=False):
    if not force and not notification_enabled(event):
        return False, "disabled"

    user_key, app_token, _ = get_pushover_credentials()
    if not user_key or not app_token:
        return False, "missing_credentials"

    try:
        response = requests.post(
            PUSHOVER_API_URL,
            data={
                "token": app_token,
                "user": user_key,
                "title": str(title)[:250],
                "message": str(message)[:1024],
            },
            timeout=10,
        )
        response.raise_for_status()
        return True, "sent"
    except requests.RequestException as exc:
        print(f"Pushover-Versand fehlgeschlagen: {exc}", flush=True)
        return False, "request_failed"
