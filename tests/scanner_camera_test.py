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

# The process loop handles a failed read, a valid frame, Ctrl+C, and cleanup.
loop_camera = Mock()
loop_camera.read.side_effect = [(False, None), (True, "loop-frame"), KeyboardInterrupt()]
scanner.create_camera = Mock(return_value=loop_camera)
scanner.Buzzer = Mock(return_value="buzzer")
scanner.init_db = Mock()
scanner.process_frame = Mock()
scanner.run()
scanner.init_db.assert_called_once()
scanner.process_frame.assert_called_once_with("loop-frame", "buzzer", set(), {})
loop_camera.release.assert_called_once()

# Sound patterns always release the PWM output.
pwm = Mock()
scanner.PWMOutputDevice = Mock(return_value=pwm)
scanner.time.sleep = Mock()
scanner.play_test_sound("success", 40)
scanner.play_test_sound("unknown", 60)
assert pwm.close.call_count == 2

# Cover the complete successful frame path including snapshot, diagnostics,
# recoverable processing error, and remote sound command.
class Frame:
    shape = (10, 10, 3)

full_camera = Mock()
full_camera.read.side_effect = [(True, Frame()), (True, Frame()), KeyboardInterrupt()]
scanner.create_camera = Mock(return_value=full_camera)
scanner.Buzzer = Mock(return_value="buzzer")
scanner.init_db = Mock()
scanner.publish_local_scanner = Mock()
scanner.write_status = Mock(return_value={"running": True})
scanner.process_frame = Mock(side_effect=[RuntimeError("decode"), None])
scanner.cv2.imwrite = Mock()
scanner.frame_path = Mock(return_value="/tmp/frame.jpg")
scanner.consume_command = Mock(return_value={"type": "sound", "pattern": "success", "volume": 25})
scanner.server_url = lambda: "https://fridge.example.net"
scanner.publish_diagnostics = Mock(side_effect=RuntimeError("offline"))
scanner.poll_command = Mock()
scanner.play_test_sound = Mock()
scanner.time.monotonic = Mock(side_effect=[0.0, 2.1, 2.2, 4.3])
scanner.run()
assert scanner.cv2.imwrite.called
assert scanner.play_test_sound.called
full_camera.release.assert_called_once()

print("All scanner camera tests passed.")
