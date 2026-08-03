"""Remote scanner client with an idempotent local offline queue."""

import json
import os
import secrets
import socket
import time
import uuid
from pathlib import Path

import requests
from zeroconf import ServiceBrowser, ServiceListener, Zeroconf

_discovered_url = None


def credentials_path():
    root = Path(os.environ.get("SCANNER_DATA_DIR", "/data"))
    return root / "scanner-network-credentials.json"


def _credentials():
    try:
        return json.loads(credentials_path().read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return {}


def _save_credentials(values):
    path = credentials_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(values), encoding="utf-8")
    temporary.replace(path)


class _DiscoveryListener(ServiceListener):
    def __init__(self):
        self.urls = []

    def add_service(self, zeroconf, service_type, name):
        info = zeroconf.get_service_info(service_type, name, timeout=1500)
        if not info:
            return
        for address in info.parsed_scoped_addresses():
            if ":" not in address:
                self.urls.append(f"http://{address}:{info.port}")

    def update_service(self, zeroconf, service_type, name):
        self.add_service(zeroconf, service_type, name)

    def remove_service(self, zeroconf, service_type, name):
        return None


def discover_server(timeout=3):
    listener = _DiscoveryListener()
    zeroconf = Zeroconf()
    browser = ServiceBrowser(zeroconf, "_smartfridge._tcp.local.", listener)
    try:
        deadline = time.monotonic() + timeout
        while not listener.urls and time.monotonic() < deadline:
            time.sleep(0.1)
        return listener.urls[0] if listener.urls else ""
    finally:
        browser.cancel()
        zeroconf.close()


def server_url():
    global _discovered_url
    configured = os.environ.get("SCANNER_SERVER_URL", "").strip().rstrip("/")
    if configured:
        return configured
    saved = str(_credentials().get("server_url", "")).strip().rstrip("/")
    if saved:
        return saved
    enabled = os.environ.get("SCANNER_AUTO_DISCOVERY", "false").lower() in {"1", "true", "yes", "on"}
    if enabled and _discovered_url is None:
        _discovered_url = discover_server()
    return _discovered_url or ""


def scanner_token():
    return os.environ.get("SCANNER_TOKEN", "").strip() or str(_credentials().get("token", "")).strip()


def ensure_pairing():
    url = server_url()
    if not url or scanner_token():
        return bool(scanner_token())
    values = _credentials()
    secret = values.get("pairing_secret") or secrets.token_urlsafe(32)
    scanner_id = os.environ.get("SCANNER_ID", "").strip()
    name = os.environ.get("SCANNER_NAME", scanner_id).strip()
    values.update({"server_url": url, "pairing_secret": secret})
    _save_credentials(values)
    try:
        requests.post(
            f"{url}/api/scanner/v1/pair",
            json={"scanner_id": scanner_id, "name": name, "pairing_secret": secret},
            timeout=5,
        ).raise_for_status()
        response = requests.post(
            f"{url}/api/scanner/v1/pair/status",
            json={"scanner_id": scanner_id, "pairing_secret": secret},
            timeout=5,
        )
        response.raise_for_status()
        result = response.json()
        if result.get("status") == "approved" and result.get("token"):
            values["token"] = result["token"]
            values.pop("pairing_secret", None)
            _save_credentials(values)
            return True
    except requests.RequestException:
        return False
    return False


def queue_path():
    scanner_id = os.environ.get("SCANNER_ID", "scanner").strip() or "scanner"
    root = Path(os.environ.get("SCANNER_DATA_DIR", "/data"))
    return root / f"offline-{scanner_id}.jsonl"


def _event(ean):
    return {
        "event_id": str(uuid.uuid4()),
        "scanner_id": os.environ.get("SCANNER_ID", "").strip(),
        "ean": str(ean),
    }


def _send(event):
    if not ensure_pairing():
        raise requests.ConnectionError("scanner pairing pending")
    response = requests.post(
        f"{server_url()}/api/scanner/v1/book",
        json=event,
        headers={"Authorization": f"Bearer {scanner_token()}"},
        timeout=5,
    )
    response.raise_for_status()
    return response.json()


def _read_queue():
    try:
        return [json.loads(line) for line in queue_path().read_text().splitlines() if line.strip()]
    except (OSError, ValueError):
        return []


def _write_queue(events):
    path = queue_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    if not events:
        path.unlink(missing_ok=True)
        return
    temporary = path.with_suffix(".tmp")
    temporary.write_text("".join(json.dumps(event) + "\n" for event in events))
    temporary.replace(path)


def flush_queue():
    remaining = []
    delivered = []
    for event in _read_queue():
        try:
            delivered.append(_send(event))
        except requests.RequestException:
            remaining.append(event)
    _write_queue(remaining)
    return delivered


def remote_book_barcode(ean):
    flush_queue()
    event = _event(ean)
    try:
        return _send(event)
    except requests.RequestException:
        events = _read_queue()
        events.append(event)
        _write_queue(events)
        return {"ok": False, "queued": True, "error": "server_unreachable"}
