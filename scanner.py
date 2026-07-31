import cv2
import sqlite3
import time
from gpiozero import Buzzer
from time import sleep
from datetime import datetime
from pyzbar.pyzbar import decode, ZBarSymbol

from database import DB, init_db
from utils.notifications import send_pushover

init_db()
buzzer = Buzzer(17)

# Barcode muss einige Frames verschwunden sein,
# bevor derselbe Barcode erneut gebucht werden darf
FRAMES_BIS_FREIGABE = 5

# Nur relevante Produkt-Barcodes erkennen
BARCODE_TYPEN = [
    ZBarSymbol.EAN13,
    ZBarSymbol.EAN8,
    ZBarSymbol.UPCA,
    ZBarSymbol.UPCE
]

# USB-Webcam öffnen
camera = cv2.VideoCapture(0)
camera.set(cv2.CAP_PROP_AUTOFOCUS, 0)
camera.set(cv2.CAP_PROP_FOCUS, 300)

# MJPEG verwenden, falls von der Webcam unterstützt
camera.set(
    cv2.CAP_PROP_FOURCC,
    cv2.VideoWriter_fourcc(*"MJPG")
)

# 720p statt 1080p für schnellere Verarbeitung
camera.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)
camera.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)

# Kamerapuffer klein halten
camera.set(cv2.CAP_PROP_BUFFERSIZE, 1)

if not camera.isOpened():
    print("FEHLER: Webcam konnte nicht geöffnet werden!")
    raise SystemExit(1)

print("Getränkekühlschrank-Scanner läuft!")
print("Auflösung: 1280x720")
print("Erlaubt: EAN-13, EAN-8, UPC-A, UPC-E")
print("Barcode vor die Kamera halten ...")
print("Beenden mit Ctrl+C")

gesperrte_barcodes = set()
nicht_gesehen_frames = {}


def buche_aus(ean):

    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row

    barcode = conn.execute(
        """
        SELECT
            pb.ean AS scan_ean,
            pb.menge AS scan_menge,
            pb.aktion AS scan_aktion,
            p.id AS produkt_id,
            p.name,
            p.bestand,
            p.mindestbestand,
            p.preis_cent,
            p.waehrung
        FROM produkt_barcodes pb
        JOIN produkte p
            ON p.id = pb.produkt_id
        WHERE pb.ean = ?
        """,
        (ean,)
    ).fetchone()

    if barcode is None:
        print(f"UNBEKANNT: EAN {ean}")
        send_pushover(
            "unknown_barcode",
            "Unbekannter Barcode",
            f"Der Barcode {ean} ist keinem Produkt zugeordnet.",
        )
        conn.close()
        return

    menge = barcode["scan_menge"]

    aktion = barcode["scan_aktion"]

    if aktion == "entnehmen":
        if barcode["bestand"] < menge:
            print(
                f"NICHT GENUG BESTAND: {barcode['name']} "
                f"| Bestand: {barcode['bestand']} "
                f"| Barcode-Menge: {menge}"
            )
            conn.close()
            return

        aenderung = -menge
        buchungsaktion = "Ausgebucht"

    elif aktion == "einlagern":
        aenderung = menge
        buchungsaktion = "Eingelagert"

    else:
        print(f"UNBEKANNTE AKTION: {aktion}")
        conn.close()
        return

    neuer_bestand = barcode["bestand"] + aenderung

    zeitpunkt = datetime.now().strftime(
        "%Y-%m-%d %H:%M:%S"
    )
    benutzer_id = None
    benutzer_name = None
    accounts_setting = conn.execute(
        """
        SELECT wert
        FROM einstellungen
        WHERE schluessel = 'benutzerkonten_aktiv'
        """
    ).fetchone()
    accounts_enabled = (
        accounts_setting
        and accounts_setting["wert"].lower()
        in ("1", "true", "yes", "on")
    )
    if accounts_enabled:
        active_user = conn.execute(
            """
            SELECT
                u.id,
                u.name,
                CAST(expiry.wert AS INTEGER) AS expires_at
            FROM einstellungen selected
            JOIN einstellungen expiry
              ON expiry.schluessel = 'aktiver_scanner_benutzer_bis'
            JOIN benutzer u
              ON u.id = CAST(selected.wert AS INTEGER)
            WHERE selected.schluessel = 'aktiver_scanner_benutzer'
              AND u.aktiv = 1
            """
        ).fetchone()
        if (
            active_user
            and active_user["expires_at"] >= int(time.time())
        ):
            benutzer_id = active_user["id"]
            benutzer_name = active_user["name"]

        required_setting = conn.execute(
            """
            SELECT wert
            FROM einstellungen
            WHERE schluessel = 'scanner_benutzer_erforderlich'
            """
        ).fetchone()
        user_required = (
            required_setting
            and required_setting["wert"].lower()
            in ("1", "true", "yes", "on")
        )
        if user_required and benutzer_id is None:
            print(
                "SCAN BLOCKIERT: Zuerst per PIN/Passwort oder NFC "
                "einen Benutzer auswählen.",
                flush=True,
            )
            conn.close()
            send_pushover(
                "scan_blocked",
                "Getränkescan blockiert",
                "Ein Getränkescan wurde ohne angemeldeten Benutzer blockiert.",
            )
            for _ in range(2):
                buzzer.on()
                sleep(0.08)
                buzzer.off()
                sleep(0.08)
            return

    conn.execute(
        """
        UPDATE produkte
        SET bestand = ?
        WHERE id = ?
        """,
        (
            neuer_bestand,
            barcode["produkt_id"]
        )
    )

    conn.execute(
        """
        INSERT INTO buchungen (
            ean,
            produkt,
            aktion,
            zeitpunkt,
            menge,
            bestand_vorher,
            bestand_nachher,
            quelle,
            einzelpreis_cent,
            waehrung,
            benutzer_id,
            benutzer_name
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            ean,
            barcode["name"],
            buchungsaktion,
            zeitpunkt,
            aenderung,
            barcode["bestand"],
            neuer_bestand,
            "scanner",
            barcode["preis_cent"],
            barcode["waehrung"],
            benutzer_id,
            benutzer_name,
        )
    )

    if accounts_enabled and aktion == "entnehmen":
        conn.execute(
            """
            UPDATE einstellungen
            SET wert = ''
            WHERE schluessel IN (
                'aktiver_scanner_benutzer',
                'aktiver_scanner_benutzer_bis'
            )
            """
        )

    conn.commit()
    conn.close()

    if aktion == "entnehmen":
        send_pushover(
            "removed",
            "Getränk entnommen",
            f"{barcode['name']}: {menge} entnommen, Bestand {neuer_bestand}.",
        )
        if neuer_bestand == 0:
            send_pushover(
                "out_of_stock",
                "Getränk leer",
                f"{barcode['name']} ist jetzt leer.",
            )
        elif (
            barcode["mindestbestand"] > 0
            and barcode["bestand"] > barcode["mindestbestand"]
            and neuer_bestand <= barcode["mindestbestand"]
        ):
            send_pushover(
                "low_stock",
                "Niedriger Bestand",
                f"{barcode['name']}: nur noch {neuer_bestand} vorhanden.",
            )
    else:
        send_pushover(
            "restocked",
            "Getränk eingelagert",
            f"{barcode['name']}: {menge} eingelagert, Bestand {neuer_bestand}.",
        )

    buzzer.on()
    sleep(0.15)
    buzzer.off()

    print(
        f"PIEP! {barcode['name']} "
        f"{buchungsaktion.lower()} "
        f"| Menge: {menge} "
        f"| Neuer Bestand: {neuer_bestand} "
        f"| Benutzer: {benutzer_name or 'nicht zugeordnet'} "
        f"| Zeit: {zeitpunkt}"
    )


try:

    while True:

        success, frame = camera.read()

        if not success:
            print("Fehler beim Lesen der Kamera")
            continue

        # Graustufen beschleunigt die Barcode-Erkennung
        gray = cv2.cvtColor(
            frame,
            cv2.COLOR_BGR2GRAY
        )

        # Nur gewünschte Barcode-Typen suchen
        barcodes = decode(
            gray,
            symbols=BARCODE_TYPEN
        )

        erkannte_barcodes = set()

        for barcode in barcodes:

            ean = barcode.data.decode("utf-8")

            erkannte_barcodes.add(ean)

            if ean not in gesperrte_barcodes:

                buche_aus(ean)

                gesperrte_barcodes.add(ean)

            # Barcode ist sichtbar
            nicht_gesehen_frames[ean] = 0


        # Prüfen, ob Barcode wieder aus dem Bild verschwunden ist
        for ean in list(gesperrte_barcodes):

            if ean not in erkannte_barcodes:

                nicht_gesehen_frames[ean] = (
                    nicht_gesehen_frames.get(ean, 0) + 1
                )

                if (
                    nicht_gesehen_frames[ean]
                    >= FRAMES_BIS_FREIGABE
                ):

                    gesperrte_barcodes.remove(ean)

                    nicht_gesehen_frames.pop(
                        ean,
                        None
                    )

                    print(
                        f"Scanner wieder bereit "
                        f"für EAN {ean}"
                    )


except KeyboardInterrupt:

    print("\nScanner beendet.")


finally:

    camera.release()

    print("Kamera freigegeben.")
