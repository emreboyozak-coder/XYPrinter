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


def test_detector_finds_repeated_cores_across_multiple_boards() -> None:
    reference = _reference_frame()
    aligner = PrintZoneAligner()
    aligner.teach(0, reference, Rectangle(80, 100, 66, 51))

    repeated = np.full((480, 800, 3), 220, dtype=np.uint8)
    for offset_x, offset_y in ((0, 0), (400, 0), (0, 240), (400, 240)):
        repeated[offset_y:offset_y + 240, offset_x:offset_x + 400] = reference
    _, measurement, status = aligner.process(repeated)

    assert measurement is not None, status
    assert "4 cores" in status
    assert abs(measurement.midpoint_x - 313.0) < 2
    assert abs(measurement.midpoint_y - 245.5) < 2


def test_context_keeps_a_plain_print_zone_distinct() -> None:
    reference = _reference_frame()
    aligner = PrintZoneAligner()
    aligner.teach(0, reference, Rectangle(80, 100, 66, 51))

    brighter = cv2.convertScaleAbs(reference, alpha=1.15, beta=12)
    _, measurement, status = aligner.process(brighter)

    assert measurement is not None, status
    assert measurement.score_1 >= 0.70


def test_taught_zones_persist_between_application_starts(tmp_path) -> None:
    reference = _reference_frame()
    path = tmp_path / "print-zone-templates.npz"
    aligner = PrintZoneAligner()
    aligner.teach(0, reference, Rectangle(80, 100, 66, 51))
    aligner.save(path)

    loaded = PrintZoneAligner()
    assert loaded.load(path) is True
    _, measurement, status = loaded.process(reference)
    assert measurement is not None, status


def test_core_center_must_be_inside_detected_pcb() -> None:
    board = Rectangle(50, 40, 200, 120)
    assert PrintZoneAligner._contains(board, (100.0, 80.0)) is True
    assert PrintZoneAligner._contains(board, (20.0, 80.0)) is False


def test_detections_are_numbered_in_visual_reading_order() -> None:
    detections = [
        (Rectangle(220, 120, 40, 30), 0.9),
        (Rectangle(200, 20, 40, 30), 0.9),
        (Rectangle(20, 125, 40, 30), 0.9),
        (Rectangle(10, 25, 40, 30), 0.9),
    ]
    ordered = PrintZoneAligner._reading_order(detections)
    assert [rectangle.x for rectangle, _ in ordered] == [10, 200, 20, 220]


def test_multiple_samples_are_saved_for_each_zone(tmp_path) -> None:
    reference = _reference_frame()
    shifted = cv2.warpAffine(reference, np.float32([[1, 0, 9], [0, 1, 4]]), (400, 240), borderValue=(220, 220, 220))
    path = tmp_path / "print-zone-templates.npz"
    aligner = PrintZoneAligner()
    aligner.teach(0, reference, Rectangle(80, 100, 66, 51))
    aligner.teach(0, shifted, Rectangle(89, 104, 66, 51), append=True)
    assert aligner.sample_counts() == (2, 0)
    aligner.save(path)

    loaded = PrintZoneAligner()
    assert loaded.load(path) is True
    assert loaded.sample_counts() == (2, 0)


def test_sample_library_accepts_many_examples(tmp_path) -> None:
    reference = _reference_frame()
    path = tmp_path / "print-zone-templates.npz"
    aligner = PrintZoneAligner()
    aligner.teach(0, reference, Rectangle(80, 100, 66, 51))
    for _ in range(20):
        aligner.teach(0, reference, Rectangle(80, 100, 66, 51), append=True)

    assert aligner.sample_counts() == (21, 0)
    aligner.save(path)
    reloaded = PrintZoneAligner()
    assert reloaded.load(path) is True
    assert reloaded.sample_counts() == (21, 0)


def test_false_detection_examples_are_persisted(tmp_path) -> None:
    reference = _reference_frame()
    path = tmp_path / "print-zone-templates.npz"
    aligner = PrintZoneAligner()
    aligner.teach(0, reference, Rectangle(80, 100, 66, 51))
    aligner.teach_negative(0, reference, Rectangle(240, 105, 66, 51))
    assert aligner.negative_counts() == (1, 0)
    aligner.save(path)

    reloaded = PrintZoneAligner()
    assert reloaded.load(path) is True
    assert reloaded.negative_counts() == (1, 0)
