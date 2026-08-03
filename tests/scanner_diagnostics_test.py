"""Scanner diagnostics state and command tests."""

import json
import os
import sys
import tempfile

sys.path.insert(0, "/app")

with tempfile.TemporaryDirectory() as directory:
    os.environ["SCANNER_DATA_DIR"] = directory
    import scanner_diagnostics

    initial = scanner_diagnostics.read_status()
    assert initial["running"] is False
    state = scanner_diagnostics.write_status(running=True, fps=24.5, detected_barcodes=["123"])
    assert state["fps"] == 24.5
    assert scanner_diagnostics.read_status()["detected_barcodes"] == ["123"]

    heartbeat = scanner_diagnostics.publish_local_scanner("kitchen-1", "Kitchen scanner")
    assert heartbeat["scanner_id"] == "kitchen-1"
    discovered = scanner_diagnostics.discover_local_scanners(now=heartbeat["updated_at"])
    assert discovered[0]["name"] == "Kitchen scanner"
    assert scanner_diagnostics.discover_local_scanners(max_age=1, now=heartbeat["updated_at"] + 2) == []
    invalid = scanner_diagnostics.discovery_dir() / "invalid.json"
    invalid.write_text(json.dumps({"scanner_id": "../bad", "updated_at": heartbeat["updated_at"]}))
    assert scanner_diagnostics.discover_local_scanners(now=heartbeat["updated_at"]) == discovered

    scanner_diagnostics.queue_sound_test("warning", 75)
    command = scanner_diagnostics.consume_command()
    assert command == {"type": "sound", "pattern": "warning", "volume": 75}
    assert scanner_diagnostics.consume_command() is None

    try:
        scanner_diagnostics.queue_sound_test("invalid", 50)
    except ValueError:
        pass
    else:
        raise AssertionError("invalid sound accepted")

print("All scanner diagnostics tests passed.")
