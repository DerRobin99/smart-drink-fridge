"""Hardware-independent tests for the read-only Nextion status display."""

import os
import sqlite3
import sys
import time

sys.path.insert(0, "/app")
os.environ.setdefault("DATABASE_PATH", "/tmp/nextion-display-unit-test.db")
os.environ.setdefault("SECRET_KEY", "ci-nextion-test-secret")

from werkzeug.security import generate_password_hash

import database
import nextion_display


assert nextion_display.safe_text('Míchèle "Cola"') == "Michele 'Cola'"

# Exercise the real database state and existing password-hash verification.
database.init_db()
conn = sqlite3.connect(database.DB)
conn.execute(
    "INSERT INTO benutzer (name, login_name, password_hash) VALUES (?, ?, ?)",
    ("Database User", "db-user", generate_password_hash("1234")),
)
user_id = conn.execute(
    "SELECT id FROM benutzer WHERE login_name = 'db-user'"
).fetchone()[0]
for key, value in (
    ("benutzerkonten_aktiv", "1"),
    ("scanner_benutzer_erforderlich", "1"),
    ("aktiver_scanner_benutzer", str(user_id)),
    ("aktiver_scanner_benutzer_bis", str(int(time.time()) + 120)),
):
    conn.execute(
        """
        INSERT INTO einstellungen (schluessel, wert) VALUES (?, ?)
        ON CONFLICT(schluessel) DO UPDATE SET wert = excluded.wert
        """,
        (key, value),
    )
conn.execute(
    """
    INSERT INTO buchungen (
        ean, produkt, aktion, menge, bestand_nachher, quelle, benutzer_name
    ) VALUES ('1', 'Database Cola', 'Ausgebucht', -1, 2, 'scanner', 'Database User')
    """
)
conn.commit()
conn.close()

real_state = nextion_display.display_state()
assert real_state["user"]["name"] == "Database User"
assert real_state["booking"]["produkt"] == "Database Cola"
assert real_state["user_required"]
selected = []
nextion_display.set_scanner_user = lambda selected_id, duration_seconds: selected.append(
    (selected_id, duration_seconds)
)
assert not nextion_display.authenticate_user_pin(user_id, "bad")
assert nextion_display.authenticate_user_pin(user_id, "1234")
assert selected == [(user_id, nextion_display.USER_SECONDS)]
assert not nextion_display.authenticate_user_pin(999999, "1234")

# Exercise serial detection, drawing, initialization, and touch packet parsing
# without opening real UART hardware.
serial_writes = []
serial_reads = [b"comok 1,NX4832K035\xff\xff\xff"]
originals = {
    "open": nextion_display.os.open,
    "close": nextion_display.os.close,
    "read": nextion_display.os.read,
    "write": nextion_display.os.write,
    "tcgetattr": nextion_display.termios.tcgetattr,
    "tcsetattr": nextion_display.termios.tcsetattr,
    "tcflush": nextion_display.termios.tcflush,
    "select": nextion_display.select.select,
}
nextion_display.os.open = lambda *args: 42
nextion_display.os.close = lambda fd: None
nextion_display.os.write = lambda fd, data: serial_writes.append(data) or len(data)
nextion_display.os.read = lambda fd, size: serial_reads.pop(0)
nextion_display.termios.tcgetattr = lambda fd: [0, 0, 0, 0, 0, 0, []]
nextion_display.termios.tcsetattr = lambda *args: None
nextion_display.termios.tcflush = lambda *args: None
nextion_display.select.select = lambda read, write, error, timeout: (
    ([42] if read and serial_reads else []),
    ([42] if write else []),
    [],
)
uart = nextion_display.Nextion("/dev/fake", 9600)
uart.initialize()
uart.button(0, 0, 80, 30, "OK")
assert any(b"baud=115200" in write for write in serial_writes)
assert any(b"tm0.en=0" in write for write in serial_writes)
serial_reads.append(b"\x67\x00\x0a\x00\x14\x00\xff\xff\xff")
assert uart.events() == [(10, 20, 0)]
uart.close()
for name, original in originals.items():
    if name == "select":
        nextion_display.select.select = original
    elif name.startswith("tc"):
        setattr(nextion_display.termios, name, original)
    else:
        setattr(nextion_display.os, name, original)


class FakeDisplay:
    def __init__(self):
        self.commands = []

    def command(self, value):
        self.commands.append(value)

    def fill(self, *args):
        self.commands.append(("fill", args))

    def text(self, *args):
        self.commands.append(("text", args))

    def button(self, *args):
        self.commands.append(("button", args))


class InitializingDisplay(FakeDisplay):
    initialize = nextion_display.Nextion.initialize


initializing = InitializingDisplay()
initializing.initialize()
assert initializing.commands[:5] == [
    "bkcmd=0",
    "ref_star",
    "page 8",
    "tm0.en=0",
    "sendxy=1",
]


state = {
    "accounts_enabled": True,
    "user_required": True,
    "user": {"id": 7, "name": "Robin"},
    "users": [
        {"id": 7, "name": "Robin"},
        {"id": 8, "name": "Michele"},
    ],
    "booking": {
        "id": 12,
        "produkt": "Cola",
        "aktion": "Ausgebucht",
        "zeitpunkt": "2026-08-01 19:10:00",
        "menge": -1,
        "bestand_nachher": 4,
        "benutzer_name": "Robin",
    },
}
nextion_display.display_state = lambda: state
display = FakeDisplay()
status = nextion_display.StatusDisplay(display)
status.render(force=True)
texts = [item[1][4] for item in display.commands if isinstance(item, tuple) and item[0] == "text"]
assert "Robin" in texts
assert "Cola" in texts
assert "-1   Bestand: 4" in texts

state["user"] = None
state["booking"] = None
status.render(force=True)
texts = [item[1][4] for item in display.commands if isinstance(item, tuple) and item[0] == "text"]
assert "NFC oder PIN erforderlich" in texts
assert "Noch kein Scan" in texts

# Render the selectable-user and PIN pages, including paging and failure paths.
state["users"] = [
    {"id": number, "name": f"User {number}"} for number in range(1, 8)
]
status.mode = "users"
status.render(force=True)
status.handle_touch(330, 290, 0)
assert status.user_page == 1
status.handle_touch(150, 290, 0)
assert status.user_page == 0
status.handle_touch(50, 290, 0)
assert status.mode == "status"

# Open user selection and select the first user.
status.handle_touch(240, 130, 0)
assert status.mode == "users"
status.handle_touch(200, 70, 0)
assert status.mode == "pin"
assert status.selected_user["id"] == 1

# Enter 1234 using the on-screen keypad and submit it.
for x, y in ((50, 120), (150, 120), (260, 120), (50, 170)):
    status.handle_touch(x, y, 0)
assert status.pin == "1234"
status.handle_touch(410, 120, 0)
assert status.pin == "123"
status.handle_touch(50, 170, 0)
assert status.pin == "1234"
nextion_display.authenticate_user_pin = lambda user_id, pin: False
status.handle_touch(410, 270, 0)
assert status.mode == "pin"
assert status.message == nextion_display.tr("display_wrong_pin")
for x, y in ((50, 120), (150, 120), (260, 120), (50, 170)):
    status.handle_touch(x, y, 0)
authenticated = []
nextion_display.authenticate_user_pin = lambda user_id, pin: authenticated.append(
    (user_id, pin)
) or True
status.handle_touch(410, 270, 0)
assert authenticated == [(1, "1234")]
assert status.mode == "status"
assert status.pin == ""

print("All Nextion display unit tests passed.")
