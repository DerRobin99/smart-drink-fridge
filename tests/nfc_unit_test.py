"""Hardware-independent tests for NFC card handling."""

import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import Mock

sys.path.insert(0, "/app")
os.environ.setdefault("DATABASE_PATH", "/tmp/nfc-unit-test.db")
os.environ.setdefault("SECRET_KEY", "ci-nfc-test-secret")

import nfc_reader

nfc_reader.server_url = lambda: ""


with tempfile.TemporaryDirectory() as runtime_dir:
    socket_file = Path(runtime_dir) / "pcscd.comm"
    pid_file = Path(runtime_dir) / "pcscd.pid"
    socket_file.touch()
    pid_file.write_text("123", encoding="utf-8")
    nfc_reader.cleanup_pcscd_runtime_files((socket_file, pid_file))
    assert not socket_file.exists()
    assert not pid_file.exists()


class FakeConnection:
    def __init__(self, result):
        self.result = result
        self.connected = False

    def connect(self):
        self.connected = True

    def transmit(self, command):
        assert command == nfc_reader.GET_UID
        return self.result


class FakeReader:
    def __init__(self, result=([0x01, 0xAB, 0xFF], 0x90, 0x00)):
        self.connection = FakeConnection(result)

    def createConnection(self):
        return self.connection


reader = FakeReader()
assert nfc_reader.read_uid(reader) == "01ABFF"
assert reader.connection.connected

try:
    nfc_reader.read_uid(FakeReader(([], 0x63, 0x00)))
except nfc_reader.CardConnectionException:
    pass
else:
    raise AssertionError("Invalid card response was accepted")

nfc_reader.readers = lambda: [reader]
assert nfc_reader.wait_for_reader() is reader

# Enrollment consumes the card before login lookup.
nfc_reader.capture_rfid_enrollment = lambda uid: True
nfc_reader.activate_uid("01ABFF")

# Disabled accounts ignore otherwise valid cards.
nfc_reader.capture_rfid_enrollment = lambda uid: False
nfc_reader.accounts_enabled = lambda: False
nfc_reader.activate_uid("01ABFF")

# Invalid card IDs are rejected before touching the database.
nfc_reader.accounts_enabled = lambda: True
nfc_reader.hash_rfid = Mock(side_effect=ValueError("invalid"))
nfc_reader.activate_uid("!")


class FakeDatabase:
    def __init__(self, user):
        self.user = user
        self.closed = False

    def execute(self, statement, params):
        assert "rfid_hash" in statement
        assert params == ("digest",)
        return self

    def fetchone(self):
        return self.user

    def close(self):
        self.closed = True


nfc_reader.hash_rfid = lambda uid: "digest"
unknown_db = FakeDatabase(None)
nfc_reader.get_db = lambda: unknown_db
nfc_reader.activate_uid("01ABFF")
assert unknown_db.closed

known_db = FakeDatabase({"id": 7, "name": "NFC Test User"})
activation = {}
nfc_reader.get_db = lambda: known_db
nfc_reader.set_scanner_user = lambda user_id, duration_seconds, source: activation.update(
    user_id=user_id,
    duration_seconds=duration_seconds,
    source=source,
)
nfc_reader.activate_uid("01ABFF")
assert known_db.closed
assert activation == {"user_id": 7, "duration_seconds": 120, "source": "nfc"}

remote = {}
nfc_reader.server_url = lambda: "http://server"
nfc_reader.remote_activate_uid = lambda uid: remote.update(uid=uid) or {
    "ok": True, "status": "activated", "user": {"name": "Remote User"}
}
nfc_reader.activate_uid("01ABFF")
assert remote == {"uid": "01ABFF"}

print("All NFC unit tests passed.")
