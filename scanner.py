"""Camera barcode scanner process."""

import cv2
from gpiozero import Buzzer
from pyzbar.pyzbar import ZBarSymbol, decode

from database import init_db
from scanner_booking import book_barcode

FRAMES_BIS_FREIGABE = 5
BARCODE_TYPEN = [ZBarSymbol.EAN13, ZBarSymbol.EAN8, ZBarSymbol.UPCA, ZBarSymbol.UPCE]


def create_camera(device=0):
    camera = cv2.VideoCapture(device)
    camera.set(cv2.CAP_PROP_AUTOFOCUS, 0)
    camera.set(cv2.CAP_PROP_FOCUS, 300)
    camera.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
    camera.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)
    camera.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)
    camera.set(cv2.CAP_PROP_BUFFERSIZE, 1)
    if not camera.isOpened():
        camera.release()
        raise RuntimeError("Webcam konnte nicht geöffnet werden.")
    return camera


def process_frame(frame, buzzer, locked, unseen_frames):
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    detected = set()
    for barcode in decode(gray, symbols=BARCODE_TYPEN):
        ean = barcode.data.decode("utf-8")
        detected.add(ean)
        if ean not in locked:
            book_barcode(ean, buzzer=buzzer)
            locked.add(ean)
        unseen_frames[ean] = 0

    for ean in list(locked):
        if ean in detected:
            continue
        unseen_frames[ean] = unseen_frames.get(ean, 0) + 1
        if unseen_frames[ean] >= FRAMES_BIS_FREIGABE:
            locked.remove(ean)
            unseen_frames.pop(ean, None)
            print(f"Scanner wieder bereit für EAN {ean}")
    return detected


def run():
    init_db()
    buzzer = Buzzer(17)
    camera = create_camera()
    locked = set()
    unseen_frames = {}
    print("Getränkekühlschrank-Scanner läuft!")
    print("Auflösung: 1280x720")
    print("Erlaubt: EAN-13, EAN-8, UPC-A, UPC-E")
    print("Barcode vor die Kamera halten ...")
    print("Beenden mit Ctrl+C")
    try:
        while True:
            success, frame = camera.read()
            if not success:
                print("Fehler beim Lesen der Kamera")
                continue
            process_frame(frame, buzzer, locked, unseen_frames)
    except KeyboardInterrupt:
        print("\nScanner beendet.")
    finally:
        camera.release()
        print("Kamera freigegeben.")


if __name__ == "__main__":
    run()
