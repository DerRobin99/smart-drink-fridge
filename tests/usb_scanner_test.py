"""USB-HID scanner selection, event decoding and user-gating tests."""

import os
import sys
import tempfile
import time
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
mixed = b"x" + b"".join(event(code) for code in (79, 80, 14, 81, 96))
barcodes, buffer, pending = usb_scanner.decode_events(mixed[1:], "123456")
assert barcodes == ["12345613"]
assert buffer == ""
assert pending == b""
ignored = event(2, value=0) + event(2, event_type=0) + b"partial"
assert usb_scanner.decode_events(ignored) == ([], "", b"partial")
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

try:
    usb_scanner.find_device("/definitely/missing/scanner")
    raise AssertionError("Missing configured scanner must fail")
except FileNotFoundError:
    pass

original_glob = usb_scanner.glob.glob
try:
    usb_scanner.glob.glob = lambda pattern: (
        ["/dev/input/by-id/a-event-kbd", "/dev/input/by-id/b-event-kbd"]
        if pattern.endswith("*-event-kbd") and "barcode" not in pattern
        and "scanner" not in pattern and "TOT2D" not in pattern
        else []
    )
    try:
        usb_scanner.find_device("")
        raise AssertionError("Ambiguous scanners must fail")
    except RuntimeError:
        pass
    usb_scanner.glob.glob = lambda pattern: ["/dev/input/event7"] if pattern.endswith("event*") else []
    assert usb_scanner.find_device("") == "/dev/input/event7"
    usb_scanner.glob.glob = lambda pattern: []
    try:
        usb_scanner.find_device("")
        raise AssertionError("Missing auto-detected scanner must fail")
    except FileNotFoundError:
        pass
finally:
    usb_scanner.glob.glob = original_glob


class FakeConnection:
    row_factory = None

    def __init__(self, settings, user=None):
        self.settings = settings
        self.user = user
        self.closed = False

    def execute(self, query, params=()):
        if "FROM einstellungen" in query:
            rows = [{"schluessel": key, "wert": value} for key, value in self.settings.items()]
            return type("Result", (), {"fetchall": lambda self: rows})()
        user = self.user
        return type("Result", (), {"fetchone": lambda self: user})()

    def close(self):
        self.closed = True


original_connect = usb_scanner.sqlite3.connect
try:
    connection = FakeConnection({
        "benutzerkonten_aktiv": "true",
        "scanner_benutzer_erforderlich": "yes",
        "aktiver_scanner_benutzer": "7",
        "aktiver_scanner_benutzer_bis": "200",
    }, {"id": 7, "name": "Robin"})
    usb_scanner.sqlite3.connect = lambda _path: connection
    state = usb_scanner.local_user_state(now=100)
    assert state["user"] == {"id": 7, "name": "Robin"}
    assert state["user_expires_at"] == 200
    assert connection.closed

    connection = FakeConnection({
        "benutzerkonten_aktiv": "true",
        "scanner_benutzer_erforderlich": "true",
        "aktiver_scanner_benutzer": "invalid",
        "aktiver_scanner_benutzer_bis": "invalid",
    })
    usb_scanner.sqlite3.connect = lambda _path: connection
    assert usb_scanner.local_user_state(now=100)["user"] is None
finally:
    usb_scanner.sqlite3.connect = original_connect

original_server_url = usb_scanner.server_url
original_remote_state = usb_scanner.remote_display_state
original_local_state = usb_scanner.local_user_state
try:
    usb_scanner.server_url = lambda: "https://fridge.example.net"
    usb_scanner.remote_display_state = lambda: {"user": {"id": 9}}
    assert usb_scanner.user_state()["user"]["id"] == 9
    usb_scanner.server_url = lambda: ""
    usb_scanner.local_user_state = lambda: {"user": None}
    assert usb_scanner.user_state()["user"] is None
finally:
    usb_scanner.server_url = original_server_url
    usb_scanner.remote_display_state = original_remote_state
    usb_scanner.local_user_state = original_local_state

with tempfile.NamedTemporaryFile() as stream:
    stream.write(data)
    stream.flush()
    original_poll = usb_scanner.select.poll
    try:
        class ReadyPoll:
            def register(self, *_args):
                pass

            def poll(self, _timeout):
                return [(1, usb_scanner.select.POLLIN)]

        usb_scanner.select.poll = ReadyPoll
        assert usb_scanner.read_one_barcode(stream.name, time.time() + 1) == "1234567890"
        assert usb_scanner.read_one_barcode(stream.name, time.time() - 1) is None
    finally:
        usb_scanner.select.poll = original_poll


class FakeBuzzer:
    def __init__(self, _pin):
        self.closed = False

    def close(self):
        self.closed = True


def exercise_run(barcode, successful=True, remote=False, scan_error=None):
    active = {
        "accounts_enabled": True,
        "user_required": True,
        "user": {"id": 7},
        "user_expires_at": int(time.time()) + 120,
    }
    states = iter([active])
    statuses = []
    usb_scanner.Buzzer = FakeBuzzer
    usb_scanner.server_url = lambda: "https://fridge.example.net" if remote else ""
    usb_scanner.init_db = lambda: None
    usb_scanner.publish_local_scanner = lambda: None
    usb_scanner.write_status = lambda **values: statuses.append(values)
    usb_scanner.consume_command = lambda: None
    usb_scanner.user_state = lambda: next(states)
    usb_scanner.find_device = lambda: "/dev/input/scanner"
    usb_scanner.book_barcode = lambda ean, buzzer=None: successful
    usb_scanner.read_status = lambda: {"running": True}
    usb_scanner.publish_diagnostics = lambda _status: None
    usb_scanner.poll_command = lambda: None
    if scan_error:
        usb_scanner.read_one_barcode = lambda *_args: (_ for _ in ()).throw(scan_error)
        usb_scanner.time.sleep = lambda _seconds: (_ for _ in ()).throw(KeyboardInterrupt())
    else:
        usb_scanner.read_one_barcode = lambda *_args: barcode
    try:
        usb_scanner.run()
    except StopIteration:
        raise AssertionError("run must handle loop termination through KeyboardInterrupt")
    assert statuses[0]["scanner_mode"] == "usb"
    assert statuses[-1] == {"running": False, "waiting_for_barcode": False}
    return statuses


originals = {name: getattr(usb_scanner, name) for name in (
    "Buzzer", "server_url", "init_db", "publish_local_scanner", "write_status",
    "consume_command", "user_state", "find_device", "book_barcode",
    "read_status", "publish_diagnostics", "poll_command", "read_one_barcode",
)}
original_sleep = usb_scanner.time.sleep
try:
    # End each successful/timeout loop when it requests the next user state.
    def stop_after_first(states):
        iterator = iter(states)
        def next_state():
            try:
                return next(iterator)
            except StopIteration:
                raise KeyboardInterrupt()
        return next_state

    active_state = {
        "accounts_enabled": True, "user_required": True,
        "user": {"id": 7}, "user_expires_at": int(time.time()) + 120,
    }
    for barcode, success in (("12345678", True), ("87654321", False), (None, True)):
        statuses = []
        usb_scanner.Buzzer = FakeBuzzer
        usb_scanner.server_url = lambda: ""
        usb_scanner.init_db = lambda: None
        usb_scanner.publish_local_scanner = lambda: None
        usb_scanner.write_status = lambda **values: statuses.append(values)
        usb_scanner.consume_command = lambda: None
        usb_scanner.user_state = stop_after_first([active_state])
        usb_scanner.find_device = lambda: "/dev/input/scanner"
        usb_scanner.read_one_barcode = lambda *_args, value=barcode: value
        usb_scanner.book_barcode = lambda _ean, buzzer=None, value=success: value
        usb_scanner.run()
        assert statuses[-1]["running"] is False

    # Exercise the recoverable scanner-error path.
    usb_scanner.user_state = lambda: active_state
    usb_scanner.find_device = lambda: (_ for _ in ()).throw(OSError("offline"))
    usb_scanner.time.sleep = lambda _seconds: (_ for _ in ()).throw(KeyboardInterrupt())
    usb_scanner.run()
finally:
    for name, value in originals.items():
        setattr(usb_scanner, name, value)
    usb_scanner.time.sleep = original_sleep

print("All USB scanner tests passed.")
