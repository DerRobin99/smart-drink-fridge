"""USB-HID barcode scanner gated by the active NFC/PIN user window."""

import glob
import os
import select
import sqlite3
import struct
import subprocess
import time
import json
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
POWER_CONTROL = os.environ.get("USB_SCANNER_POWER_CONTROL", "false").lower() in {
    "1", "true", "yes", "on"
}
DATA_DIR = Path(os.environ.get("SCANNER_DATA_DIR", "/data"))


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


def power_target_path():
    return DATA_DIR / "usb-scanner-power.json"


def discover_power_target(device):
    """Derive uhubctl's hub location and port from an input device."""
    event = Path(device).resolve().name
    current = (Path("/sys/class/input") / event / "device").resolve()
    for node in (current, *current.parents):
        if (node / "idVendor").is_file() and (node / "idProduct").is_file():
            usb_name = node.name
            if "." in usb_name:
                hub, port = usb_name.rsplit(".", 1)
            elif "-" in usb_name:
                hub, port = usb_name.rsplit("-", 1)
            else:
                continue
            if port.isdigit():
                target = {"hub": hub, "port": int(port)}
                power_target_path().parent.mkdir(parents=True, exist_ok=True)
                power_target_path().write_text(json.dumps(target), encoding="utf-8")
                return target
    raise RuntimeError(f"USB-Hub und Port konnten für {device} nicht ermittelt werden.")


def load_power_target(device=None):
    try:
        target = json.loads(power_target_path().read_text(encoding="utf-8"))
        if target.get("hub") and int(target.get("port", 0)) > 0:
            return {"hub": str(target["hub"]), "port": int(target["port"])}
    except (OSError, ValueError, TypeError):
        pass
    if device:
        return discover_power_target(device)
    raise RuntimeError("Kein gespeichertes USB-Power-Ziel vorhanden.")


def set_usb_power(target, enabled):
    # Older Raspberry Pi boards expose their internal USB ports as if they
    # supported per-port switching, while the power rail is actually shared.
    # Refuse that internal first-level hub so switching the scanner cannot
    # disconnect the NFC reader (or Ethernet on some models).
    model_path = Path("/proc/device-tree/model")
    try:
        is_raspberry_pi = "Raspberry Pi" in model_path.read_text(
            encoding="utf-8", errors="ignore"
        )
    except OSError:
        is_raspberry_pi = False
    if is_raspberry_pi and target["hub"].count(".") == 0:
        raise RuntimeError(
            "Interner Raspberry-Pi-USB-Hub wird aus Sicherheitsgründen nicht "
            "geschaltet; bitte einen externen Hub mit einzeln schaltbaren "
            "Ports verwenden."
        )
    action = "on" if enabled else "off"
    result = subprocess.run(
        ["uhubctl", "-l", target["hub"], "-p", str(target["port"]), "-a", action],
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    if result.returncode:
        raise RuntimeError((result.stderr or result.stdout or "uhubctl failed").strip())
    return True


def wait_for_device(device, timeout=8):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if Path(device).exists():
            return device
        time.sleep(0.2)
    raise TimeoutError(f"USB-Scanner erschien nach dem Einschalten nicht: {device}")


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
    power_target = None
    if POWER_CONTROL:
        try:
            initial_device = find_device()
            power_target = load_power_target(initial_device)
        except FileNotFoundError:
            power_target = load_power_target()
        set_usb_power(power_target, False)
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
                if power_target:
                    set_usb_power(power_target, True)
                    device = wait_for_device(DEVICE or find_device())
                else:
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
                try:
                    ean = read_one_barcode(device, deadline)
                finally:
                    if power_target:
                        set_usb_power(power_target, False)
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
        if power_target:
            try:
                set_usb_power(power_target, False)
            except Exception:
                pass
        buzzer.close()
        write_status(running=False, waiting_for_barcode=False)


if __name__ == "__main__":
    run()
