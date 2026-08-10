"""USB-HID barcode scanner gated by the active NFC/PIN user window."""

import glob
import os
import select
import sqlite3
import struct
import time
from pathlib import Path

from gpiozero import Buzzer

from database import DB, init_db
from scanner_booking import book_barcode
from scanner_client import (
    poll_command,
    publish_diagnostics,
    remote_display_state,
    server_url,
)
from scanner_diagnostics import consume_command, publish_local_scanner, read_status, write_status


EVENT = struct.Struct("llHHI")
EV_KEY = 1
KEY_ENTER = 28
KEY_KPENTER = 96
KEY_BACKSPACE = 14
KEYS = {
    2: "1", 3: "2", 4: "3", 5: "4", 6: "5",
    7: "6", 8: "7", 9: "8", 10: "9", 11: "0",
    79: "1", 80: "2", 81: "3", 75: "4", 76: "5",
    77: "6", 71: "7", 72: "8", 73: "9", 82: "0",
}
MIN_LENGTH = max(1, int(os.environ.get("USB_SCANNER_MIN_LENGTH", "8")))
DEVICE = os.environ.get("USB_SCANNER_DEVICE", "").strip()
POLL_SECONDS = max(0.2, float(os.environ.get("USB_SCANNER_USER_POLL_SECONDS", "1")))


def find_device(configured=DEVICE):
    """Return a stable configured path or auto-detect a single HID keyboard."""
    if configured:
        path = Path(configured)
        if path.exists():
            return str(path)
        raise FileNotFoundError(f"Konfigurierter USB-Scanner fehlt: {configured}")

    preferred = []
    for pattern in ("*barcode*-event-kbd", "*scanner*-event-kbd", "*TOT2D*-event-kbd"):
        preferred.extend(glob.glob(f"/dev/input/by-id/{pattern}"))
    candidates = sorted(set(preferred))
    if not candidates:
        candidates = sorted(glob.glob("/dev/input/by-id/*-event-kbd"))
    if len(candidates) == 1:
        return candidates[0]
    if not candidates:
        events = sorted(glob.glob("/dev/input/event*"))
        if len(events) == 1:
            return events[0]
        raise FileNotFoundError("Kein eindeutiger USB-HID-Scanner gefunden.")
    raise RuntimeError(
        "Mehrere HID-Tastaturen gefunden; USB_SCANNER_DEVICE muss gesetzt werden: "
        + ", ".join(candidates)
    )


def local_user_state(now=None):
    now = int(time.time() if now is None else now)
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        """SELECT schluessel, wert FROM einstellungen WHERE schluessel IN (
               'benutzerkonten_aktiv', 'scanner_benutzer_erforderlich',
               'aktiver_scanner_benutzer', 'aktiver_scanner_benutzer_bis'
           )"""
    ).fetchall()
    settings = {row["schluessel"]: row["wert"] for row in rows}
    enabled = lambda value: str(value or "").lower() in {"1", "true", "yes", "on"}
    accounts = enabled(settings.get("benutzerkonten_aktiv"))
    required = accounts and enabled(settings.get("scanner_benutzer_erforderlich"))
    try:
        user_id = int(settings.get("aktiver_scanner_benutzer", "0"))
        expires_at = int(settings.get("aktiver_scanner_benutzer_bis", "0"))
    except (TypeError, ValueError):
        user_id = expires_at = 0
    user = None
    if accounts and user_id and expires_at >= now:
        row = conn.execute(
            "SELECT id, name FROM benutzer WHERE id=? AND aktiv=1", (user_id,)
        ).fetchone()
        user = dict(row) if row else None
    conn.close()
    return {
        "accounts_enabled": accounts,
        "user_required": required,
        "user": user,
        "user_expires_at": expires_at if user else None,
    }


def user_state():
    return remote_display_state() if server_url() else local_user_state()


def session_key(state):
    if not state.get("accounts_enabled") or not state.get("user_required"):
        return "ungated"
    user = state.get("user")
    if not user:
        return None
    return user.get("id"), state.get("user_expires_at")


def decode_events(data, buffer=""):
    """Decode Linux input events into complete scanner lines."""
    barcodes = []
    usable = len(data) - (len(data) % EVENT.size)
    for offset in range(0, usable, EVENT.size):
        _sec, _usec, event_type, code, value = EVENT.unpack_from(data, offset)
        if event_type != EV_KEY or value != 1:
            continue
        if code in (KEY_ENTER, KEY_KPENTER):
            if len(buffer) >= MIN_LENGTH and buffer.isdigit():
                barcodes.append(buffer)
            buffer = ""
        elif code == KEY_BACKSPACE:
            buffer = buffer[:-1]
        elif code in KEYS:
            buffer += KEYS[code]
    return barcodes, buffer, data[usable:]


def read_one_barcode(device, deadline):
    """Open the HID device only for the authenticated scan window."""
    barcode_buffer = ""
    pending = b""
    with open(device, "rb", buffering=0) as stream:
        poller = select.poll()
        poller.register(stream, select.POLLIN)
        while time.time() < deadline:
            events = poller.poll(min(500, max(1, int((deadline - time.time()) * 1000))))
            if not events:
                continue
            pending += os.read(stream.fileno(), EVENT.size * 64)
            barcodes, barcode_buffer, pending = decode_events(pending, barcode_buffer)
            if barcodes:
                return barcodes[0]
    return None


def run():
    if not server_url():
        init_db()
    publish_local_scanner()
    buzzer = Buzzer(17)
    consumed_session = None
    last_publish = 0.0
    write_status(running=True, scanner_mode="usb", started_at=int(time.time()), last_error=None)
    print("USB-Barcodescanner läuft; warte auf NFC-/PIN-Anmeldung …", flush=True)
    try:
        while True:
            try:
                state = user_state()
                current_session = session_key(state)
                now = time.monotonic()
                command = consume_command()
                if server_url() and now - last_publish >= 2:
                    try:
                        publish_diagnostics(read_status())
                        command = poll_command() or command
                    except Exception as exc:
                        print(f"Diagnose-Synchronisierung fehlgeschlagen: {exc}", flush=True)
                    last_publish = now
                if current_session is None:
                    # The current v1.10 server does not expose the expiry value.
                    # Seeing the logged-out state resets the consumed session so
                    # the same user can authenticate again for the next drink.
                    consumed_session = None
                if current_session is None or current_session == consumed_session:
                    time.sleep(POLL_SECONDS)
                    continue
                expires_at = state.get("user_expires_at")
                deadline = float(expires_at) if expires_at else time.time() + 120
                device = find_device()
                write_status(
                    running=True,
                    scanner_mode="usb",
                    usb_device=device,
                    waiting_for_barcode=True,
                    active_until=int(deadline),
                    last_error=None,
                )
                print(f"Scanner für Benutzer freigegeben: {device}", flush=True)
                ean = read_one_barcode(device, deadline)
                if ean:
                    successful = book_barcode(ean, buzzer=buzzer)
                    write_status(
                        waiting_for_barcode=False,
                        last_scan_at=int(time.time()),
                        last_success_at=int(time.time()) if successful else None,
                        last_success_ean=ean if successful else None,
                    )
                    if successful:
                        consumed_session = current_session
                        print(f"Scan abgeschlossen: {ean}; Scanner wieder gesperrt.", flush=True)
                else:
                    consumed_session = current_session
                    write_status(waiting_for_barcode=False)
                    print("Scannerfenster nach 120 Sekunden geschlossen.", flush=True)
            except (OSError, RuntimeError, ValueError) as exc:
                write_status(last_error=str(exc)[:300], last_error_at=int(time.time()))
                print(f"USB-Scannerfehler: {exc}", flush=True)
                time.sleep(2)

    except KeyboardInterrupt:
        print("USB-Scanner beendet.", flush=True)
    finally:
        buzzer.close()
        write_status(running=False, waiting_for_barcode=False)


if __name__ == "__main__":
    run()
