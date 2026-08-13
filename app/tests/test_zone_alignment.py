import cv2
import numpy as np

from marker.vision.zone_alignment import PrintZoneAligner, Rectangle


def _reference_frame() -> np.ndarray:
    frame = np.full((240, 400, 3), 220, dtype=np.uint8)
    cv2.rectangle(frame, (80, 100), (145, 150), (30, 30, 30), -1)
    cv2.circle(frame, (100, 120), 8, (180, 180, 180), -1)
    cv2.rectangle(frame, (240, 105), (305, 155), (45, 45, 45), -1)
    cv2.line(frame, (250, 115), (295, 145), (190, 190, 190), 3)
    return frame


def test_zone_alignment_reports_translation_error() -> None:
    reference = _reference_frame()
    aligner = PrintZoneAligner()
    aligner.teach(0, reference, Rectangle(80, 100, 66, 51))
    aligner.teach(1, reference, Rectangle(240, 105, 66, 51))

    transform = np.float32([[1, 0, 12], [0, 1, -7]])
    moved = cv2.warpAffine(reference, transform, (400, 240), borderValue=(220, 220, 220))
    _, measurement, status = aligner.process(moved)

    assert measurement is not None, status
    assert abs(measurement.error_x + 12) < 2
    assert abs(measurement.error_y - 7) < 2


def test_context_keeps_a_plain_print_zone_distinct() -> None:
    reference = _reference_frame()
    aligner = PrintZoneAligner()
    aligner.teach(0, reference, Rectangle(80, 100, 66, 51))
    aligner.teach(1, reference, Rectangle(240, 105, 66, 51))

    brighter = cv2.convertScaleAbs(reference, alpha=1.15, beta=12)
    _, measurement, status = aligner.process(brighter)

    assert measurement is not None, status
    assert measurement.score_1 >= 0.70
    assert measurement.score_2 >= 0.70


def test_taught_zones_persist_between_application_starts(tmp_path) -> None:
    reference = _reference_frame()
    path = tmp_path / "print-zone-templates.npz"
    aligner = PrintZoneAligner()
    aligner.teach(0, reference, Rectangle(80, 100, 66, 51))
    aligner.teach(1, reference, Rectangle(240, 105, 66, 51))
    aligner.save(path)

    loaded = PrintZoneAligner()
    assert loaded.load(path) is True
    _, measurement, status = loaded.process(reference)
    assert measurement is not None, status
