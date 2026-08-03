"""Shared scanner health state and command channel."""

import json
import os
import re
import socket
import time
from pathlib import Path


def data_dir():
    return Path(os.environ.get("SCANNER_DATA_DIR", "/data"))


def status_path():
    return data_dir() / "scanner-diagnostics.json"


def frame_path():
    return data_dir() / "scanner-last-frame.jpg"


def command_path():
    return data_dir() / "scanner-command.json"


def discovery_dir():
    return data_dir() / "scanner-discovery"


def _scanner_id(value=None):
    value = (value or os.environ.get("SCANNER_ID", "local-scanner")).strip()
    if not re.fullmatch(r"[A-Za-z0-9._-]{2,64}", value):
        raise ValueError("invalid scanner id")
    return value


def publish_local_scanner(scanner_id=None, name=None):
    """Publish a non-secret heartbeat for discovery by a co-located web app."""
    scanner_id = _scanner_id(scanner_id)
    payload = {
        "scanner_id": scanner_id,
        "name": (name or os.environ.get("SCANNER_NAME") or scanner_id).strip()[:100],
        "hostname": socket.gethostname()[:255],
        "updated_at": int(time.time()),
    }
    directory = discovery_dir()
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{scanner_id}.json"
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    temporary.replace(path)
    return payload


def discover_local_scanners(max_age=90, now=None):
    """Return valid, recent scanner heartbeats from the shared data volume."""
    now = int(time.time() if now is None else now)
    discovered = []
    try:
        paths = list(discovery_dir().glob("*.json"))
    except OSError:
        return discovered
    for path in paths:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            scanner_id = _scanner_id(payload.get("scanner_id"))
            updated_at = int(payload.get("updated_at", 0))
            if path.stem != scanner_id or updated_at <= 0 or now - updated_at > max_age:
                continue
            discovered.append({
                "scanner_id": scanner_id,
                "name": str(payload.get("name") or scanner_id).strip()[:100],
                "hostname": str(payload.get("hostname") or "").strip()[:255],
                "updated_at": updated_at,
            })
        except (OSError, ValueError, TypeError):
            continue
    return sorted(discovered, key=lambda item: item["scanner_id"].lower())


def read_status():
    try:
        return json.loads(status_path().read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return {
            "running": False,
            "fps": 0,
            "last_decode_ms": None,
            "detected_barcodes": [],
            "last_scan_at": None,
            "last_success_at": None,
            "last_success_ean": None,
            "last_error": None,
            "last_error_at": None,
            "updated_at": None,
        }


def write_status(**changes):
    state = read_status()
    state.update(changes)
    state["updated_at"] = int(time.time())
    path = status_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")
    temporary.replace(path)
    return state


def queue_sound_test(pattern, volume):
    if pattern not in {"success", "warning", "error"}:
        raise ValueError("invalid sound pattern")
    volume = min(100, max(10, int(volume)))
    path = command_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(
        json.dumps({"type": "sound", "pattern": pattern, "volume": volume}),
        encoding="utf-8",
    )
    temporary.replace(path)


def consume_command():
    path = command_path()
    try:
        command = json.loads(path.read_text(encoding="utf-8"))
        path.unlink(missing_ok=True)
        return command
    except (OSError, ValueError, TypeError):
        return None
