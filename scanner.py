"""Camera barcode scanner process."""

import time
import cv2
from gpiozero import Buzzer, PWMOutputDevice
from pyzbar.pyzbar import ZBarSymbol, decode

from database import init_db
from scanner_booking import book_barcode
from scanner_diagnostics import consume_command, frame_path, publish_local_scanner, read_status, write_status
from scanner_client import poll_command, publish_diagnostics, server_url

FRAMES_BIS_FREIGABE = 5
BARCODE_TYPEN = [ZBarSymbol.EAN13, ZBarSymbol.EAN8, ZBarSymbol.UPCA, ZBarSymbol.UPCE]
_last_decode_ms = None
_last_detected = []
_last_scan_at = None


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
    global _last_decode_ms, _last_detected, _last_scan_at
    decode_started = time.monotonic()
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    detected = set()
    for barcode in decode(gray, symbols=BARCODE_TYPEN):
        ean = barcode.data.decode("utf-8")
        detected.add(ean)
        if ean not in locked:
            successful = book_barcode(ean, buzzer=buzzer)
            if successful:
                write_status(
                    last_success_at=int(time.time()),
                    last_success_ean=ean,
                    last_error=None,
                )
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
    _last_detected = sorted(detected)
    _last_decode_ms = round((time.monotonic() - decode_started) * 1000, 1)
    if detected:
        _last_scan_at = int(time.time())
    return detected


def play_test_sound(pattern, volume):
    output = PWMOutputDevice(17, frequency=1800)
    patterns = {
        "success": [(0.10, 1)],
        "warning": [(0.08, 2)],
        "error": [(0.16, 3)],
    }
    duration, count = patterns.get(pattern, patterns["warning"])
    try:
        for index in range(count):
            output.value = volume / 100
            time.sleep(duration)
            output.off()
            if index + 1 < count:
                time.sleep(0.07)
    finally:
        output.close()


def run():
    init_db()
    publish_local_scanner()
    buzzer = Buzzer(17)
    camera = create_camera()
    locked = set()
    unseen_frames = {}
    frames = 0
    fps_started = time.monotonic()
    last_snapshot = 0.0
    last_remote_publish = 0.0
    write_status(running=True, started_at=int(time.time()), last_error=None)
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
                write_status(last_error="camera_read_failed", last_error_at=int(time.time()))
                continue
            try:
                process_frame(frame, buzzer, locked, unseen_frames)
            except Exception as exc:
                write_status(last_error=str(exc)[:300], last_error_at=int(time.time()))
                print(f"Scannerfehler: {exc}", flush=True)
            frames += 1
            now = time.monotonic()
            elapsed = now - fps_started
            if elapsed >= 1:
                publish_local_scanner()
                state = write_status(
                    fps=round(frames / elapsed, 1),
                    running=True,
                    last_decode_ms=_last_decode_ms,
                    detected_barcodes=_last_detected,
                    last_scan_at=_last_scan_at,
                )
                frames, fps_started = 0, now
            if now - last_snapshot >= 2 and hasattr(frame, "shape"):
                cv2.imwrite(str(frame_path()), frame)
                last_snapshot = now
            command = consume_command()
            if server_url() and now - last_remote_publish >= 2:
                try:
                    publish_diagnostics(read_status(), frame_path())
                    command = poll_command() or command
                except Exception as exc:
                    print(f"Diagnose-Synchronisierung fehlgeschlagen: {exc}", flush=True)
                last_remote_publish = now
            if command and command.get("type") == "sound":
                play_test_sound(command.get("pattern", "warning"), int(command.get("volume", 60)))
    except KeyboardInterrupt:
        print("\nScanner beendet.")
    finally:
        camera.release()
        write_status(running=False)
        print("Kamera freigegeben.")


if __name__ == "__main__":
    run()
