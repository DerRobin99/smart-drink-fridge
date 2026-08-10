"""Scanner status and PIN login UI for a Nextion NX4832K035."""

import os
import select
import sqlite3
import termios
import time
import unicodedata

from werkzeug.security import check_password_hash

from database import DB, init_db
from scanner_client import remote_display_login, remote_display_state, server_url
from translation import normalize_language, translate
from utils.auth import set_scanner_user


PORT = os.environ.get("NEXTION_PORT", "/dev/serial0")
BAUD = int(os.environ.get("NEXTION_BAUD", "9600"))
END = b"\xff\xff\xff"
TRUE_VALUES = {"1", "true", "yes", "on"}
USER_SECONDS = int(os.environ.get("NEXTION_USER_SECONDS", "120"))
LANGUAGE = normalize_language(os.environ.get("NEXTION_LANGUAGE", "de"))

WHITE = 65535
NAVY = 1024
PANEL = 2113
MUTED = 33840
ACCENT = 2047
GREEN = 2016
RED = 63488
ORANGE = 64800

PIXEL_FONT = {
    " ": ("00000",) * 7,
    "A": ("01110", "10001", "10001", "11111", "10001", "10001", "10001"),
    "B": ("11110", "10001", "10001", "11110", "10001", "10001", "11110"),
    "C": ("01111", "10000", "10000", "10000", "10000", "10000", "01111"),
    "D": ("11110", "10001", "10001", "10001", "10001", "10001", "11110"),
    "E": ("11111", "10000", "10000", "11110", "10000", "10000", "11111"),
    "F": ("11111", "10000", "10000", "11110", "10000", "10000", "10000"),
    "G": ("01111", "10000", "10000", "10111", "10001", "10001", "01111"),
    "H": ("10001", "10001", "10001", "11111", "10001", "10001", "10001"),
    "I": ("11111", "00100", "00100", "00100", "00100", "00100", "11111"),
    "J": ("00111", "00010", "00010", "00010", "10010", "10010", "01100"),
    "K": ("10001", "10010", "10100", "11000", "10100", "10010", "10001"),
    "L": ("10000", "10000", "10000", "10000", "10000", "10000", "11111"),
    "M": ("10001", "11011", "10101", "10101", "10001", "10001", "10001"),
    "N": ("10001", "11001", "10101", "10011", "10001", "10001", "10001"),
    "O": ("01110", "10001", "10001", "10001", "10001", "10001", "01110"),
    "P": ("11110", "10001", "10001", "11110", "10000", "10000", "10000"),
    "Q": ("01110", "10001", "10001", "10001", "10101", "10010", "01101"),
    "R": ("11110", "10001", "10001", "11110", "10100", "10010", "10001"),
    "S": ("01111", "10000", "10000", "01110", "00001", "00001", "11110"),
    "T": ("11111", "00100", "00100", "00100", "00100", "00100", "00100"),
    "U": ("10001", "10001", "10001", "10001", "10001", "10001", "01110"),
    "V": ("10001", "10001", "10001", "10001", "10001", "01010", "00100"),
    "W": ("10001", "10001", "10001", "10101", "10101", "10101", "01010"),
    "X": ("10001", "10001", "01010", "00100", "01010", "10001", "10001"),
    "Y": ("10001", "10001", "01010", "00100", "00100", "00100", "00100"),
    "Z": ("11111", "00001", "00010", "00100", "01000", "10000", "11111"),
    "0": ("01110", "10001", "10011", "10101", "11001", "10001", "01110"),
    "1": ("00100", "01100", "00100", "00100", "00100", "00100", "01110"),
    "2": ("01110", "10001", "00001", "00010", "00100", "01000", "11111"),
    "3": ("11110", "00001", "00001", "01110", "00001", "00001", "11110"),
    "4": ("00010", "00110", "01010", "10010", "11111", "00010", "00010"),
    "5": ("11111", "10000", "10000", "11110", "00001", "00001", "11110"),
    "6": ("01110", "10000", "10000", "11110", "10001", "10001", "01110"),
    "7": ("11111", "00001", "00010", "00100", "01000", "01000", "01000"),
    "8": ("01110", "10001", "10001", "01110", "10001", "10001", "01110"),
    "9": ("01110", "10001", "10001", "01111", "00001", "00001", "01110"),
    "-": ("00000", "00000", "00000", "11111", "00000", "00000", "00000"),
    "+": ("00000", "00100", "00100", "11111", "00100", "00100", "00000"),
    "/": ("00001", "00010", "00010", "00100", "01000", "01000", "10000"),
    ":": ("00000", "00100", "00100", "00000", "00100", "00100", "00000"),
    ".": ("00000", "00000", "00000", "00000", "00000", "00100", "00100"),
    "<": ("00010", "00100", "01000", "10000", "01000", "00100", "00010"),
    ">": ("01000", "00100", "00010", "00001", "00010", "00100", "01000"),
    "*": ("00000", "10101", "01110", "11111", "01110", "10101", "00000"),
    "?": ("01110", "10001", "00001", "00010", "00100", "00000", "00100"),
}


def safe_text(value, limit=40):
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(character for character in text if not unicodedata.combining(character))
    text = text.encode("ascii", "replace").decode("ascii")
    return text.replace('"', "'")[:limit]


def tr(key):
    return translate(key, LANGUAGE)


def _enabled(value):
    return bool(value and str(value).lower() in TRUE_VALUES)


def display_state(now=None):
    """Read account state, active user, selectable users and latest scan."""
    if server_url():
        return remote_display_state()
    now = int(time.time() if now is None else now)
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    settings = {
        row["schluessel"]: row["wert"]
        for row in conn.execute(
            """
            SELECT schluessel, wert FROM einstellungen
            WHERE schluessel IN (
                'benutzerkonten_aktiv',
                'scanner_benutzer_erforderlich',
                'aktiver_scanner_benutzer',
                'aktiver_scanner_benutzer_bis',
                'display_show_user',
                'display_show_booking',
                'display_show_inventory',
                'display_rotate_seconds'
            )
            """
        ).fetchall()
    }
    accounts = _enabled(settings.get("benutzerkonten_aktiv"))
    required = accounts and _enabled(settings.get("scanner_benutzer_erforderlich"))
    users = []
    user = None
    active_until = 0
    if accounts:
        users = conn.execute(
            "SELECT id, name FROM benutzer WHERE aktiv = 1 ORDER BY name COLLATE NOCASE"
        ).fetchall()
        try:
            active_until = int(settings.get("aktiver_scanner_benutzer_bis", "0"))
            active_id = int(settings.get("aktiver_scanner_benutzer", "0"))
        except (TypeError, ValueError):
            active_until = active_id = 0
        if active_id and active_until >= now:
            user = conn.execute(
                "SELECT id, name FROM benutzer WHERE id = ? AND aktiv = 1",
                (active_id,),
            ).fetchone()

    booking = conn.execute(
        """
        SELECT id, produkt, aktion, zeitpunkt, menge, bestand_nachher,
               benutzer_name
        FROM buchungen
        WHERE quelle = 'scanner' AND storniert = 0
        ORDER BY id DESC LIMIT 1
        """
    ).fetchone()
    inventory = conn.execute(
        """
        SELECT COUNT(*) AS products,
               COALESCE(SUM(bestand), 0) AS units,
               COALESCE(SUM(CASE WHEN bestand <= mindestbestand THEN 1 ELSE 0 END), 0) AS low
        FROM produkte
        """
    ).fetchone()
    conn.close()
    try:
        rotate_seconds = min(120, max(3, int(settings.get("display_rotate_seconds", "10"))))
    except (TypeError, ValueError):
        rotate_seconds = 10
    return {
        "accounts_enabled": accounts,
        "user_required": required,
        "user": dict(user) if user else None,
        "user_expires_at": active_until if user else None,
        "users": [dict(row) for row in users],
        "booking": dict(booking) if booking else None,
        "inventory": dict(inventory),
        "show_user": _enabled(settings.get("display_show_user", "1")),
        "show_booking": _enabled(settings.get("display_show_booking", "1")),
        "show_inventory": _enabled(settings.get("display_show_inventory", "0")),
        "rotate_seconds": rotate_seconds,
    }


def authenticate_user_pin(user_id, pin):
    """Verify the existing password/PIN hash and select the scanner user."""
    if server_url():
        try:
            return remote_display_login(user_id, pin, USER_SECONDS)
        except Exception as exc:
            print(f"Display-Server nicht erreichbar: {exc}", flush=True)
            return False
    if len(pin) < 4:
        return False
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    user = conn.execute(
        "SELECT id, password_hash FROM benutzer WHERE id = ? AND aktiv = 1",
        (user_id,),
    ).fetchone()
    conn.close()
    if user is None or not check_password_hash(user["password_hash"], pin):
        return False
    set_scanner_user(user["id"], duration_seconds=USER_SECONDS, source="display")
    return True


class Nextion:
    def __init__(self, port=PORT, baud=BAUD):
        self.fd = os.open(port, os.O_RDWR | os.O_NOCTTY | os.O_NONBLOCK)
        self.buffer = bytearray()
        detected_baud = None
        for candidate in dict.fromkeys((baud, 115200, 9600)):
            self._set_speed(candidate)
            termios.tcflush(self.fd, termios.TCIOFLUSH)
            # A probe sent at the wrong baud rate can leave undecodable bytes
            # in the Nextion command buffer.  Terminate that stale command at
            # the newly selected speed before asking for the device identity.
            # Without this resynchronisation a display already switched to
            # 115200 baud can be missed forever when NEXTION_BAUD is 9600.
            os.write(self.fd, END * 4)
            time.sleep(0.05)
            for _ in range(2):
                os.write(self.fd, b"connect" + END)
                end = time.monotonic() + 0.8
                response = bytearray()
                while time.monotonic() < end:
                    ready, _, _ = select.select([self.fd], [], [], 0.1)
                    if ready:
                        response.extend(os.read(self.fd, 4096))
                if b"comok" in response:
                    detected_baud = candidate
                    break
            if detected_baud is not None:
                break
        if detected_baud is None:
            self.close()
            raise OSError("Nextion antwortet weder mit 9600 noch 115200 Baud")
        if detected_baud != 115200:
            os.write(self.fd, b"baud=115200" + END)
            time.sleep(0.15)
            self._set_speed(115200)
            termios.tcflush(self.fd, termios.TCIOFLUSH)

    def _set_speed(self, baud):
        attrs = termios.tcgetattr(self.fd)
        speed = getattr(termios, f"B{baud}")
        attrs[0] = attrs[1] = attrs[3] = 0
        attrs[2] = termios.CS8 | termios.CREAD | termios.CLOCAL
        attrs[4] = attrs[5] = speed
        termios.tcsetattr(self.fd, termios.TCSANOW, attrs)

    def close(self):
        os.close(self.fd)

    def command(self, value):
        data = value.encode("ascii", "replace") + END
        while data:
            try:
                written = os.write(self.fd, data)
                data = data[written:]
            except BlockingIOError:
                select.select([], [self.fd], [], 0.2)

    def fill(self, x, y, width, height, color):
        self.command(f"fill {x},{y},{width},{height},{color}")

    def text(self, x, y, width, height, value, color=WHITE, background=PANEL,
             horizontal=0, vertical=1):
        value = safe_text(value).upper()
        self.fill(x, y, width, height, background)
        scale = 3 if height >= 25 else 2
        while scale > 1 and len(value) * 6 * scale > width:
            scale -= 1
        max_characters = max(1, width // (6 * scale))
        value = value[:max_characters]
        text_width = len(value) * 6 * scale - scale
        text_height = 7 * scale
        start_x = x if horizontal == 0 else x + (width - text_width) // 2
        if horizontal == 2:
            start_x = x + width - text_width
        start_y = y if vertical == 0 else y + (height - text_height) // 2
        if vertical == 2:
            start_y = y + height - text_height

        for char_index, character in enumerate(value):
            glyph = PIXEL_FONT.get(character, PIXEL_FONT["?"])
            glyph_x = start_x + char_index * 6 * scale
            for row_index, row in enumerate(glyph):
                column = 0
                while column < 5:
                    if row[column] == "0":
                        column += 1
                        continue
                    run_start = column
                    while column < 5 and row[column] == "1":
                        column += 1
                    self.fill(
                        glyph_x + run_start * scale,
                        start_y + row_index * scale,
                        (column - run_start) * scale,
                        scale,
                        color,
                    )

    def button(self, x, y, width, height, label, color=ACCENT):
        self.fill(x, y, width, height, color)
        self.text(x, y, width, height, label, WHITE, color, 1, 1)

    def initialize(self):
        self.command("bkcmd=0")
        # Recover if a previous diagnostic session paused screen refresh.
        self.command("ref_star")
        # The factory NX4832K035 demo continuously changes pages using tm0.
        # Reuse its font resources, but stop that timer before drawing our UI.
        self.command("page 8")
        self.command("tm0.en=0")
        self.command("sendxy=1")
        self.command("thsp=0")
        self.command("dim=80")
        self.command(f"cls {NAVY}")

    def events(self, timeout=0.2):
        ready, _, _ = select.select([self.fd], [], [], timeout)
        if ready:
            self.buffer.extend(os.read(self.fd, 4096))
        events = []
        while END in self.buffer:
            index = self.buffer.index(END)
            packet = bytes(self.buffer[:index])
            del self.buffer[: index + 3]
            if len(packet) == 6 and packet[0] == 0x67:
                events.append(((packet[1] << 8) | packet[2],
                               (packet[3] << 8) | packet[4], packet[5]))
        return events


class StatusDisplay:
    def __init__(self, display):
        self.display = display
        self.mode = "status"
        self.user_page = 0
        self.selected_user = None
        self.pin = ""
        self.message = ""
        self.message_until = 0.0
        self.last_signature = None
        self.status_page = "main"
        self.last_page_change = time.monotonic()

    def header(self, title=None):
        title = title or tr("display_title")
        self.display.command(f"cls {NAVY}")
        self.display.fill(0, 0, 480, 48, PANEL)
        self.display.text(12, 5, 456, 38, title, ACCENT, PANEL, 1, 1)

    def render_status(self, state):
        self.header()
        d = self.display
        user = state["user"]
        booking = state["booking"]
        d.fill(8, 56, 464, 92, PANEL)
        if state["show_user"]:
            d.text(18, 60, 444, 24, tr("display_active_user"), MUTED, PANEL, 1, 1)
        if not state["accounts_enabled"]:
            user_label, user_color = tr("display_accounts_disabled"), MUTED
        elif user:
            user_label, user_color = user["name"], ACCENT
        elif state["user_required"]:
            user_label, user_color = tr("display_nfc_or_pin_required"), ORANGE
        else:
            user_label, user_color = tr("display_unassigned"), MUTED
        if state["show_user"]:
            d.text(18, 84, 444, 32, user_label, user_color, PANEL, 1, 1)
        if state["show_user"] and state["accounts_enabled"] and not user:
            d.button(130, 116, 220, 28, tr("display_pin_login"), ACCENT)

        d.fill(8, 156, 464, 156, PANEL)
        if state["show_booking"]:
            d.text(18, 160, 444, 24, tr("display_last_scanner_booking"), MUTED, PANEL, 1, 1)
        if not state["show_booking"]:
            d.text(18, 215, 444, 42, tr("display_booking_hidden"), MUTED, PANEL, 1, 1)
        elif booking is None:
            d.text(18, 215, 444, 42, tr("display_no_scan"), MUTED, PANEL, 1, 1)
        else:
            amount = booking["menge"] if booking["menge"] is not None else -1
            prefix = f"{amount:+d}" if isinstance(amount, int) else str(amount)
            d.text(18, 190, 444, 42, booking["produkt"], GREEN, PANEL, 1, 1)
            d.text(18, 232, 444, 32,
                   f"{prefix}   {tr('display_stock')}: {booking['bestand_nachher']}",
                   WHITE, PANEL, 1, 1)
            d.text(18, 270, 444, 30,
                   booking["benutzer_name"] or tr("display_unassigned"),
                   MUTED, PANEL, 1, 1)
        if time.monotonic() < self.message_until:
            d.fill(8, 282, 464, 30, PANEL)
            d.text(18, 282, 444, 30, self.message, ORANGE, PANEL, 1, 1)

    def render_inventory(self, state):
        self.header(tr("display_inventory"))
        inventory = state["inventory"]
        for y, label, value, color in (
            (66, tr("display_products"), inventory["products"], ACCENT),
            (142, tr("display_units"), inventory["units"], GREEN),
            (218, tr("display_low_stock"), inventory["low"], ORANGE),
        ):
            self.display.fill(18, y, 444, 62, PANEL)
            self.display.text(30, y + 4, 270, 54, label, MUTED, PANEL, 0, 1)
            self.display.text(310, y + 4, 130, 54, str(value), color, PANEL, 2, 1)

    def render_users(self, state):
        self.header(tr("display_select_user"))
        users = state["users"]
        pages = max(1, (len(users) + 4) // 5)
        self.user_page = min(self.user_page, pages - 1)
        visible = users[self.user_page * 5 : self.user_page * 5 + 5]
        for index, user in enumerate(visible):
            y = 56 + index * 43
            self.display.button(18, y, 444, 37, user["name"], PANEL)
        self.display.button(10, 278, 92, 34, tr("display_back"), MUTED)
        if self.user_page > 0:
            self.display.button(112, 278, 70, 34, "<", ACCENT)
        self.display.text(190, 278, 100, 34,
                          f"{self.user_page + 1}/{pages}", WHITE, NAVY, 1, 1)
        if self.user_page + 1 < pages:
            self.display.button(298, 278, 70, 34, ">", ACCENT)

    def render_pin(self):
        self.header(safe_text(self.selected_user["name"], 24))
        masked = "*" * len(self.pin) if self.pin else tr("display_enter_pin")
        self.display.fill(18, 54, 320, 38, PANEL)
        self.display.text(18, 54, 320, 38, masked, WHITE, PANEL, 1, 1)
        for digit, x, y in (
            ("1", 18, 100), ("2", 126, 100), ("3", 234, 100),
            ("4", 18, 151), ("5", 126, 151), ("6", 234, 151),
            ("7", 18, 202), ("8", 126, 202), ("9", 234, 202),
            ("0", 126, 253),
        ):
            self.display.button(x, y, 96, 43, digit, PANEL)
        self.display.button(352, 100, 110, 43, tr("display_delete"), MUTED)
        self.display.button(352, 160, 110, 43, tr("display_back"), MUTED)
        self.display.button(352, 253, 110, 43, tr("display_sign_in"), GREEN)
        if time.monotonic() < self.message_until:
            self.display.text(342, 211, 130, 30, self.message, RED, NAVY, 1, 1)

    def render(self, force=False):
        state = display_state()
        if (
            self.mode == "status"
            and state["show_inventory"]
            and time.monotonic() - self.last_page_change >= state["rotate_seconds"]
        ):
            self.status_page = "inventory" if self.status_page == "main" else "main"
            self.last_page_change = time.monotonic()
            force = True
        signature = (
            self.mode, self.status_page, self.user_page, self.selected_user["id"] if self.selected_user else None,
            len(self.pin), state["user"]["id"] if state["user"] else None,
            state["booking"]["id"] if state["booking"] else None,
            tuple((user["id"], user["name"]) for user in state["users"]),
            state["show_user"], state["show_booking"], state["show_inventory"],
            tuple(state["inventory"].items()),
            self.message if time.monotonic() < self.message_until else "",
        )
        if not force and signature == self.last_signature:
            return
        self.last_signature = signature
        if self.mode == "users":
            self.render_users(state)
        elif self.mode == "pin":
            self.render_pin()
        elif self.status_page == "inventory":
            self.render_inventory(state)
        else:
            self.render_status(state)

    def handle_touch(self, x, y, pressed):
        if pressed:
            return
        state = display_state()
        if self.mode == "status":
            if self.status_page == "inventory":
                self.status_page = "main"
                self.last_page_change = time.monotonic()
            elif state["accounts_enabled"] and not state["user"] and 105 <= y <= 150:
                self.mode = "users"
        elif self.mode == "users":
            users = state["users"]
            pages = max(1, (len(users) + 4) // 5)
            if y >= 270:
                if x < 108:
                    self.mode = "status"
                elif x < 190 and self.user_page > 0:
                    self.user_page -= 1
                elif x > 290 and self.user_page + 1 < pages:
                    self.user_page += 1
            elif 52 <= y < 271:
                index = self.user_page * 5 + (y - 56) // 43
                if 0 <= index < len(users):
                    self.selected_user = users[index]
                    self.pin = ""
                    self.mode = "pin"
        elif self.mode == "pin":
            if x >= 342:
                if 90 <= y < 150:
                    self.pin = self.pin[:-1]
                elif 150 <= y < 220:
                    self.pin = ""
                    self.mode = "users"
                elif y >= 240:
                    if authenticate_user_pin(self.selected_user["id"], self.pin):
                        self.pin = ""
                        self.mode = "status"
                        self.message = tr("display_signed_in")
                        self.message_until = time.monotonic() + 2
                    else:
                        self.pin = ""
                        self.message = tr("display_wrong_pin")
                        self.message_until = time.monotonic() + 2
            else:
                columns = (18, 126, 234)
                rows = (100, 151, 202)
                for row_index, row_y in enumerate(rows):
                    for column_index, column_x in enumerate(columns):
                        if column_x <= x < column_x + 96 and row_y <= y < row_y + 43:
                            digit = str(row_index * 3 + column_index + 1)
                            if len(self.pin) < 32:
                                self.pin += digit
                if 126 <= x < 222 and 253 <= y < 310 and len(self.pin) < 32:
                    self.pin += "0"
        self.last_signature = None

    def run(self):
        self.display.initialize()
        try:
            while True:
                for event in self.display.events():
                    self.handle_touch(*event)
                self.render()
                time.sleep(0.08)
        finally:
            self.display.close()


def run():
    if not server_url():
        init_db()
    while True:
        try:
            StatusDisplay(Nextion()).run()
        except (OSError, termios.error) as exc:
            print(f"Nextion nicht erreichbar: {exc}; neuer Versuch in 3 Sekunden", flush=True)
            time.sleep(3)


if __name__ == "__main__":
    run()
