"""USB-HID scanner selection, event decoding and user-gating tests."""

import os
import sys
import tempfile
from pathlib import Path

container_root = Path("/app")
sys.path.insert(0, str(container_root if container_root.is_dir() else Path(__file__).resolve().parents[1]))
import usb_scanner


def event(code, value=1, event_type=usb_scanner.EV_KEY):
    return usb_scanner.EVENT.pack(0, 0, event_type, code, value)


data = b"".join(event(code) for code in (2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 28))
barcodes, buffer, pending = usb_scanner.decode_events(data)
assert barcodes == ["1234567890"]
assert buffer == ""
assert pending == b""

short = b"".join(event(code) for code in (2, 3, 28))
assert usb_scanner.decode_events(short)[0] == []
assert usb_scanner.session_key({"accounts_enabled": True, "user_required": True, "user": None}) is None
assert usb_scanner.session_key({
    "accounts_enabled": True,
    "user_required": True,
    "user": {"id": 7},
    "user_expires_at": 123,
}) == (7, 123)
assert usb_scanner.session_key({
    "accounts_enabled": True,
    "user_required": True,
    "user": {"id": 7},
}) == (7, None)
assert usb_scanner.session_key({"accounts_enabled": False, "user_required": False}) == "ungated"

with tempfile.TemporaryDirectory() as directory:
    device = os.path.join(directory, "scanner-event-kbd")
    open(device, "wb").close()
    assert usb_scanner.find_device(device) == device

calls = []
usb_scanner.subprocess.run = lambda command, **kwargs: calls.append(command) or type(
    "Result", (), {"returncode": 0, "stdout": "", "stderr": ""}
)()
assert usb_scanner.set_usb_power({"hub": "1-1", "port": 2}, False)
assert calls == [["uhubctl", "-l", "1-1", "-p", "2", "-a", "off"]]

original_read_text = usb_scanner.Path.read_text
usb_scanner.Path.read_text = lambda self, **kwargs: (
    "Raspberry Pi 3 Model B Plus Rev 1.3" if str(self) == "/proc/device-tree/model"
    else original_read_text(self, **kwargs)
)
try:
    try:
        usb_scanner.set_usb_power({"hub": "1-1", "port": 2}, False)
        raise AssertionError("Internal Raspberry Pi hub must be rejected")
    except RuntimeError as exc:
        assert "Interner Raspberry-Pi-USB-Hub" in str(exc)
finally:
    usb_scanner.Path.read_text = original_read_text

print("All USB scanner tests passed.")
