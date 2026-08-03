"""Shared scanner health state and command channel."""

import json
import os
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
