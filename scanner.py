import cv2
from gpiozero import Buzzer
from pyzbar.pyzbar import decode, ZBarSymbol

from database import init_db
from scanner_booking import book_barcode

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

                book_barcode(ean, buzzer=buzzer)

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
