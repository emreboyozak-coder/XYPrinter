import cv2
import numpy as np

from marker.vision.fiducials import detect_fiducial_pair, draw_fiducial_overlay


def test_detects_two_circular_fiducials() -> None:
    frame = np.full((400, 600, 3), 255, dtype=np.uint8)
    cv2.circle(frame, (150, 200), 20, (0, 0, 0), -1)
    cv2.circle(frame, (450, 220), 20, (0, 0, 0), -1)

    pair = detect_fiducial_pair(frame)

    assert pair is not None
    assert abs(pair.left.x - 150) < 5
    assert abs(pair.right.x - 450) < 5
    assert abs(pair.angle_degrees - 3.8) < 2


def test_overlay_marks_a_detected_pair() -> None:
    frame = np.full((200, 300, 3), 255, dtype=np.uint8)
    cv2.circle(frame, (70, 100), 15, (0, 0, 0), -1)
    cv2.circle(frame, (230, 100), 15, (0, 0, 0), -1)

    pair = detect_fiducial_pair(frame)
    overlay = draw_fiducial_overlay(frame, pair)

    assert pair is not None
    assert not np.array_equal(frame, overlay)
