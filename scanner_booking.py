"""Barcode booking logic shared by the camera scanner and tests."""

import sqlite3
import time
from datetime import datetime
from time import sleep

from database import DB
from location_inventory import location_stock, recalculate_product_stock, resolve_location
from scanner_client import remote_book_barcode, server_url
from utils.notifications import send_pushover
from utils.apns import send_mobile_push


def _beep(buzzer, count=1, duration=0.15):
    if buzzer is None:
        return
    for _ in range(count):
        buzzer.on()
        sleep(duration)
        buzzer.off()
        if count > 1:
            sleep(0.08)


def _return(details, return_details):
    return details if return_details else bool(details.get("ok"))


def book_barcode(
    ean,
    buzzer=None,
    scanner_id=None,
    location_id=None,
    source="scanner",
    return_details=False,
    user_id=None,
    user_name=None,
):
    if server_url() and scanner_id is None and location_id is None:
        details = remote_book_barcode(ean)
        if details.get("ok"):
            _beep(buzzer)
        elif details.get("queued"):
            _beep(buzzer, count=2, duration=0.08)
        return _return(details, return_details)

    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    barcode = conn.execute(
        """
        SELECT pb.menge AS scan_menge, pb.aktion AS scan_aktion,
               p.id AS produkt_id, p.name, p.bestand, p.mindestbestand, p.sollbestand,
               p.preis_cent, p.waehrung
        FROM produkt_barcodes pb
        JOIN produkte p ON p.id = pb.produkt_id
        WHERE pb.ean = ?
        """,
        (ean,),
    ).fetchone()

    if barcode is None:
        conn.close()
        print(f"UNBEKANNT: EAN {ean}")
        send_pushover("unknown_barcode", "Unbekannter Barcode", f"Der Barcode {ean} ist keinem Produkt zugeordnet.")
        return _return({"ok": False, "error": "unknown_barcode", "ean": ean}, return_details)

    location = resolve_location(conn, scanner_id=scanner_id, location_id=location_id)
    stock = location_stock(conn, barcode, location["location_id"])
    current_stock = stock["bestand"]

    quantity = barcode["scan_menge"]
    action = barcode["scan_aktion"]
    if action == "entnehmen":
        if current_stock < quantity:
            conn.close()
            print(f"NICHT GENUG BESTAND: {barcode['name']} | Bestand: {current_stock} | Barcode-Menge: {quantity}")
            return _return({"ok": False, "error": "insufficient_stock", "stock": current_stock}, return_details)
        change, booking_action = -quantity, "Ausgebucht"
    elif action == "einlagern":
        change, booking_action = quantity, "Eingelagert"
    else:
        conn.close()
        print(f"UNBEKANNTE AKTION: {action}")
        return _return({"ok": False, "error": "invalid_action"}, return_details)

    accounts_row = conn.execute(
        "SELECT wert FROM einstellungen WHERE schluessel = 'benutzerkonten_aktiv'"
    ).fetchone()
    accounts_enabled = bool(accounts_row and accounts_row["wert"].lower() in ("1", "true", "yes", "on"))
    if accounts_enabled:
        if user_id is None:
            active_user = conn.execute(
                """
                SELECT u.id, u.name, CAST(expiry.wert AS INTEGER) AS expires_at
                FROM einstellungen selected
                JOIN einstellungen expiry ON expiry.schluessel = 'aktiver_scanner_benutzer_bis'
                JOIN benutzer u ON u.id = CAST(selected.wert AS INTEGER)
                WHERE selected.schluessel = 'aktiver_scanner_benutzer' AND u.aktiv = 1
                """
            ).fetchone()
            if active_user and active_user["expires_at"] >= int(time.time()):
                user_id, user_name = active_user["id"], active_user["name"]
        required = conn.execute(
            "SELECT wert FROM einstellungen WHERE schluessel = 'scanner_benutzer_erforderlich'"
        ).fetchone()
        if required and required["wert"].lower() in ("1", "true", "yes", "on") and user_id is None:
            conn.close()
            print("SCAN BLOCKIERT: Zuerst per PIN/Passwort oder NFC einen Benutzer auswählen.", flush=True)
            send_pushover("scan_blocked", "Getränkescan blockiert", "Ein Getränkescan wurde ohne angemeldeten Benutzer blockiert.")
            _beep(buzzer, count=2, duration=0.08)
            return _return({"ok": False, "error": "user_required"}, return_details)

    new_stock = current_stock + change
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    conn.execute(
        "UPDATE standort_bestaende SET bestand=? WHERE produkt_id=? AND standort_id=?",
        (new_stock, barcode["produkt_id"], location["location_id"]),
    )
    total_stock = recalculate_product_stock(conn, barcode["produkt_id"])
    conn.execute(
        """
        INSERT INTO buchungen (
            ean, produkt, aktion, zeitpunkt, menge, bestand_vorher,
            bestand_nachher, quelle, einzelpreis_cent, waehrung,
            benutzer_id, benutzer_name, scanner_id, standort_id, standort_name
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (ean, barcode["name"], booking_action, timestamp, change, current_stock, new_stock,
         source, barcode["preis_cent"], barcode["waehrung"], user_id, user_name,
         location.get("scanner_id"), location["location_id"], location["location_name"]),
    )
    if accounts_enabled and action == "entnehmen":
        conn.execute("UPDATE einstellungen SET wert = '' WHERE schluessel IN ('aktiver_scanner_benutzer', 'aktiver_scanner_benutzer_bis')")
    conn.commit()
    conn.close()

    if action == "entnehmen":
        send_pushover("removed", "Getränk entnommen", f"{barcode['name']}: {quantity} entnommen, Bestand {new_stock}.")
        if new_stock == 0:
            send_pushover("out_of_stock", "Getränk leer", f"{barcode['name']} ist jetzt leer.")
        elif stock["mindestbestand"] > 0 and current_stock > stock["mindestbestand"] >= new_stock:
            send_pushover("low_stock", "Niedriger Bestand", f"{barcode['name']}: nur noch {new_stock} vorhanden.")
            send_mobile_push(
                "low_stock",
                "Low stock",
                f"{barcode['name']}: only {new_stock} remaining.",
            )
    else:
        send_pushover("restocked", "Getränk eingelagert", f"{barcode['name']}: {quantity} eingelagert, Bestand {new_stock}.")
    _beep(buzzer)
    print(f"PIEP! {barcode['name']} {booking_action.lower()} | Menge: {quantity} | Standort: {location['location_name']} | Neuer Bestand: {new_stock} | Benutzer: {user_name or 'nicht zugeordnet'} | Zeit: {timestamp}")
    return _return({
        "ok": True,
        "ean": ean,
        "product": barcode["name"],
        "change": change,
        "location_id": location["location_id"],
        "location": location["location_name"],
        "location_stock": new_stock,
        "total_stock": total_stock,
    }, return_details)
