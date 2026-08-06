import subprocess
import time
from pathlib import Path

from smartcard.Exceptions import CardConnectionException, NoCardException
from smartcard.System import readers
from smartcard.pcsc.PCSCExceptions import EstablishContextException

from database import init_db
from scanner_client import remote_activate_uid, server_url
from utils.auth import (
    accounts_enabled,
    capture_rfid_enrollment,
    hash_rfid,
    set_scanner_user,
)
from utils.db import get_db


GET_UID = [0xFF, 0xCA, 0x00, 0x00, 0x00]
PCSCD_RUNTIME_FILES = (
    "/run/pcscd/pcscd.comm",
    "/run/pcscd/pcscd.pid",
)


def cleanup_pcscd_runtime_files(paths=PCSCD_RUNTIME_FILES):
    """Remove sockets and PID files left behind by an unclean container stop."""
    for path in paths:
        try:
            Path(path).unlink(missing_ok=True)
        except OSError as exc:
            print(f"PC/SC-Laufzeitdatei konnte nicht entfernt werden: {exc}", flush=True)


def activate_uid(uid):
    if server_url():
        try:
            result = remote_activate_uid(uid)
            status = result.get("status")
            if status == "activated":
                print(f"NFC-Benutzer aktiviert: {result['user']['name']}", flush=True)
            elif status == "enrolled":
                print("NFC-Chip für Benutzerkonto eingelesen.", flush=True)
            else:
                print(f"NFC-Anmeldung abgelehnt: {status}", flush=True)
        except Exception as exc:
            print(f"NFC-Server nicht erreichbar: {exc}", flush=True)
        return
    if capture_rfid_enrollment(uid):
        print("NFC-Chip für Benutzerkonto eingelesen.", flush=True)
        return

    if not accounts_enabled():
        print("NFC ignoriert: Benutzerkonten sind deaktiviert.", flush=True)
        return

    try:
        digest = hash_rfid(uid)
    except ValueError:
        print("Ungültige NFC-Karten-ID.", flush=True)
        return

    conn = get_db()
    user = conn.execute(
        """
        SELECT id, name
        FROM benutzer
        WHERE rfid_hash = ? AND aktiv = 1
        """,
        (digest,),
    ).fetchone()
    conn.close()

    if user is None:
        print(f"Unbekannte NFC-Karte: {uid}", flush=True)
        return

    set_scanner_user(user["id"], duration_seconds=120, source="nfc")
    print(
        f"NFC-Benutzer aktiviert: {user['name']} "
        "(nächster Getränkescan innerhalb von 120 Sekunden)",
        flush=True,
    )


def wait_for_reader():
    while True:
        try:
            available = readers()
        except EstablishContextException:
            print("Warte auf PC/SC-Dienst …", flush=True)
            time.sleep(1)
            continue
        if available:
            reader = available[0]
            print(f"PC/SC-NFC-Leser bereit: {reader}", flush=True)
            return reader
        print("Warte auf PC/SC-NFC-Leser …", flush=True)
        time.sleep(2)


def read_uid(reader):
    connection = reader.createConnection()
    connection.connect()
    data, sw1, sw2 = connection.transmit(GET_UID)
    if (sw1, sw2) != (0x90, 0x00) or not data:
        raise CardConnectionException(
            f"NFC-UID konnte nicht gelesen werden: {sw1:02X}{sw2:02X}"
        )
    return "".join(f"{byte:02X}" for byte in data)


def run():
    if not server_url():
        init_db()
    cleanup_pcscd_runtime_files()
    pcscd = subprocess.Popen(
        ["pcscd", "--foreground", "--disable-polkit"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.STDOUT,
    )
    last_uid = None
    last_seen = 0.0

    try:
        reader = wait_for_reader()
        while True:
            try:
                uid = read_uid(reader)
                now = time.monotonic()
                if uid != last_uid or now - last_seen > 3:
                    activate_uid(uid)
                last_uid = uid
                last_seen = now
                time.sleep(0.4)
            except (NoCardException, CardConnectionException):
                if time.monotonic() - last_seen > 1:
                    last_uid = None
                time.sleep(0.25)
            except Exception as exc:
                print(f"NFC-Lesefehler: {exc}", flush=True)
                time.sleep(2)
                reader = wait_for_reader()
    finally:
        pcscd.terminate()
        pcscd.wait(timeout=5)


if __name__ == "__main__":
    run()
