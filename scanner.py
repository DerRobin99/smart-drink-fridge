import cv2
import sqlite3
from gpiozero import Buzzer
from time import sleep
from datetime import datetime
from pyzbar.pyzbar import decode, ZBarSymbol

from database import DB, init_db

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


def pushover_nachricht(titel, nachricht):
    user = os.environ.get("PUSHOVER_USER")
    token = os.environ.get("PUSHOVER_TOKEN")

    if not user or not token:
        print("WARNUNG: Pushover-Zugangsdaten fehlen.")
        return

    try:
        response = requests.post(
            "https://api.pushover.net/1/messages.json",
            data={
                "token": token,
                "user": user,
                "title": titel,
                "message": nachricht
            },
            timeout=10
        )

        response.raise_for_status()
        print("PUSH gesendet.")

    except Exception as e:
        print(f"FEHLER beim Pushover-Versand: {e}")



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
            p.bestand
        FROM produkt_barcodes pb
        JOIN produkte p
            ON p.id = pb.produkt_id
        WHERE pb.ean = ?
        """,
        (ean,)
    ).fetchone()

    if barcode is None:
        print(f"UNBEKANNT: EAN {ean}")
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
            quelle
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            ean,
            barcode["name"],
            buchungsaktion,
            zeitpunkt,
            aenderung,
            barcode["bestand"],
            neuer_bestand,
            "scanner"
        )
    )

    conn.commit()
    conn.close()

    # Warnung, wenn der Bestand die Schwelle 3 erreicht
    # oder von oberhalb 3 auf unterhalb 3 fällt.
    if (
        barcode["bestand"] > 3
        and neuer_bestand <= 3
    ):
        pushover_warnung(
            barcode["name"],
            neuer_bestand
        )

    buzzer.on()
    sleep(0.15)
    buzzer.off()

    print(
        f"PIEP! {barcode['name']} "
        f"{buchungsaktion.lower()} "
        f"| Menge: {menge} "
        f"| Neuer Bestand: {neuer_bestand} "
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
