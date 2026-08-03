"""Remote scanner client with an idempotent local offline queue."""

import json
import os
import uuid
from pathlib import Path

import requests


def server_url():
    return os.environ.get("SCANNER_SERVER_URL", "").strip().rstrip("/")


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
    response = requests.post(
        f"{server_url()}/api/scanner/v1/book",
        json=event,
        headers={"Authorization": f"Bearer {os.environ.get('SCANNER_TOKEN', '')}"},
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
