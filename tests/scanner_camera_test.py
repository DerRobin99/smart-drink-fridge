"""Camera-loop tests with synthetic frames and barcodes."""

import sys
from types import SimpleNamespace
from unittest.mock import Mock

sys.path.insert(0, "/app")
import scanner

scanner.cv2.cvtColor = lambda frame, mode: frame
bookings = []
scanner.book_barcode = lambda ean, buzzer=None: bookings.append(ean)
visible = [SimpleNamespace(data=b"12345678")]
scanner.decode = lambda frame, symbols=None: visible
locked, unseen = set(), {}
assert scanner.process_frame("frame", None, locked, unseen) == {"12345678"}
assert bookings == ["12345678"]
scanner.process_frame("frame", None, locked, unseen)
assert bookings == ["12345678"]
visible.clear()
for _ in range(scanner.FRAMES_BIS_FREIGABE):
    scanner.process_frame("frame", None, locked, unseen)
assert not locked and not unseen

camera = Mock()
camera.isOpened.return_value = True
scanner.cv2.VideoCapture = Mock(return_value=camera)
scanner.cv2.VideoWriter_fourcc = Mock(return_value=123)
assert scanner.create_camera() is camera
assert camera.set.call_count == 6
closed = Mock()
closed.isOpened.return_value = False
scanner.cv2.VideoCapture.return_value = closed
try:
    scanner.create_camera()
except RuntimeError:
    pass
else:
    raise AssertionError("Closed camera accepted")
closed.release.assert_called_once()

print("All scanner camera tests passed.")
