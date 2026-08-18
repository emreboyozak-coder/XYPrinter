"""Persistent multi-sample detection for repeated PCB cores."""

from __future__ import annotations

import threading
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np


@dataclass(frozen=True)
class Rectangle:
    x: int
    y: int
    width: int
    height: int

    @property
    def center(self) -> tuple[float, float]:
        return (self.x + self.width / 2.0, self.y + self.height / 2.0)


@dataclass(frozen=True)
class AlignmentMeasurement:
    midpoint_x: float
    midpoint_y: float
    error_x: float
    error_y: float
    score_1: float
    score_2: float
    primary_x: float | None = None
    primary_y: float | None = None


@dataclass(frozen=True)
class ZoneSample:
    """One lighting/position example of a zone's surrounding visual context."""

    template: np.ndarray
    target_offset_x: int
    target_offset_y: int


@dataclass(frozen=True)
class LearnedZone:
    """Fixed target guide and all visual examples learned for that target."""

    guide: Rectangle
    samples: tuple[ZoneSample, ...]


class PrintZoneAligner:
    """Detects repeated PCBs and finds cores only inside those boards."""

    _MIN_SCORE = 0.68
    _CONTEXT_PADDING_PX = 0
    _MAX_DETECTIONS_PER_SAMPLE = 100

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._zones: list[LearnedZone | None] = [None, None]
        self._negative_samples: list[list[np.ndarray]] = [[], []]
        self._last_detection_counts = (0, 0)
        self._last_numbered_core_centers: list[tuple[int, int, float, float]] = []

    def teach(self, index: int, frame: np.ndarray, rectangle: Rectangle, *, append: bool = False) -> None:
        if index not in (0, 1):
            raise ValueError("Core type index must be 0 or 1")
        if rectangle.width < 12 or rectangle.height < 12:
            raise ValueError("Select a larger PCB core area")

        height, width = frame.shape[:2]
        if rectangle.x < 0 or rectangle.y < 0 or rectangle.x + rectangle.width > width or rectangle.y + rectangle.height > height:
            raise ValueError("Selected zone is outside the camera frame")

        left = max(0, rectangle.x - self._CONTEXT_PADDING_PX)
        top = max(0, rectangle.y - self._CONTEXT_PADDING_PX)
        right = min(width, rectangle.x + rectangle.width + self._CONTEXT_PADDING_PX)
        bottom = min(height, rectangle.y + rectangle.height + self._CONTEXT_PADDING_PX)
        sample = ZoneSample(
            template=self._normalize(frame[top:bottom, left:right]),
            target_offset_x=rectangle.x - left,
            target_offset_y=rectangle.y - top,
        )
        with self._lock:
            existing = self._zones[index]
            if append and existing is not None:
                self._zones[index] = LearnedZone(existing.guide, (*existing.samples, sample))
            else:
                self._zones[index] = LearnedZone(rectangle, (sample,))

    def sample_counts(self) -> tuple[int, int]:
        with self._lock:
            return tuple(len(zone.samples) if zone else 0 for zone in self._zones)  # type: ignore[return-value]

    def teach_negative(self, index: int, frame: np.ndarray, rectangle: Rectangle) -> None:
        if index not in (0, 1):
            raise ValueError("Core type index must be 0 or 1")
        if rectangle.width < 12 or rectangle.height < 12:
            raise ValueError("Select a larger false detection area")
        height, width = frame.shape[:2]
        if rectangle.x < 0 or rectangle.y < 0 or rectangle.x + rectangle.width > width or rectangle.y + rectangle.height > height:
            raise ValueError("Selected false detection is outside the camera frame")
        sample = self._normalize(frame[rectangle.y:rectangle.y + rectangle.height, rectangle.x:rectangle.x + rectangle.width])
        with self._lock:
            if self._zones[index] is None:
                raise ValueError("Teach the PCB core before adding false examples")
            self._negative_samples[index].append(sample)

    def negative_counts(self) -> tuple[int, int]:
        with self._lock:
            return tuple(len(samples) for samples in self._negative_samples)  # type: ignore[return-value]

    def detection_counts(self) -> tuple[int, int]:
        with self._lock:
            return self._last_detection_counts

    def numbered_core_centers(self) -> list[tuple[int, int, float, float]]:
        with self._lock:
            return list(self._last_numbered_core_centers)

    def clear(self) -> None:
        with self._lock:
            self._zones = [None, None]
            self._negative_samples = [[], []]
            self._last_detection_counts = (0, 0)
            self._last_numbered_core_centers = []

    def clear_type(self, index: int) -> None:
        if index not in (0, 1):
            raise ValueError("Learning type index must be 0 or 1")
        with self._lock:
            self._zones[index] = None
            self._negative_samples[index] = []
            self._last_detection_counts = (0, 0)
            self._last_numbered_core_centers = []

    def save(self, path: Path) -> None:
        """Persist the taught core and its positive/negative examples."""
        with self._lock:
            if all(zone is None for zone in self._zones):
                return
            zones = list(self._zones)
            negative_samples = [list(samples) for samples in self._negative_samples]
        arrays: dict[str, np.ndarray] = {}
        for index, zone in enumerate(zones):
            arrays[f"present_{index}"] = np.array([1 if zone is not None else 0])
            if zone is None:
                continue
            arrays[f"guide_{index}"] = np.array([zone.guide.x, zone.guide.y, zone.guide.width, zone.guide.height])
            arrays[f"sample_count_{index}"] = np.array([len(zone.samples)])
            for sample_index, sample in enumerate(zone.samples):
                arrays[f"template_{index}_{sample_index}"] = sample.template
                arrays[f"offset_{index}_{sample_index}"] = np.array([sample.target_offset_x, sample.target_offset_y])
            arrays[f"negative_count_{index}"] = np.array([len(negative_samples[index])])
            for sample_index, sample in enumerate(negative_samples[index]):
                arrays[f"negative_{index}_{sample_index}"] = sample
        path.parent.mkdir(parents=True, exist_ok=True)
        np.savez_compressed(path, **arrays)

    def load(self, path: Path) -> bool:
        """Load all saved examples; also accepts the earlier one-sample format."""
        if not path.exists():
            return False
        try:
            with np.load(path, allow_pickle=False) as data:
                zones: list[LearnedZone | None] = []
                negative_samples: list[list[np.ndarray]] = []
                for index in (0, 1):
                    present_key = f"present_{index}"
                    if present_key in data and int(data[present_key][0]) == 0:
                        zones.append(None)
                        negative_samples.append([])
                        continue
                    guide = Rectangle(*[int(value) for value in data[f"guide_{index}"]])
                    sample_count_key = f"sample_count_{index}"
                    count = int(data[sample_count_key][0]) if sample_count_key in data else 1
                    samples = []
                    for sample_index in range(count):
                        template_key = f"template_{index}_{sample_index}" if sample_count_key in data else f"template_{index}"
                        offset_key = f"offset_{index}_{sample_index}" if sample_count_key in data else f"offset_{index}"
                        offsets = [int(value) for value in data[offset_key]]
                        samples.append(ZoneSample(data[template_key].copy(), offsets[0], offsets[1]))
                    zones.append(LearnedZone(guide, tuple(samples)))
                    negative_count_key = f"negative_count_{index}"
                    negative_count = int(data[negative_count_key][0]) if negative_count_key in data else 0
                    negative_samples.append([data[f"negative_{index}_{sample_index}"].copy() for sample_index in range(negative_count)])
        except (KeyError, OSError, ValueError):
            return False
        with self._lock:
            self._zones = zones
            self._negative_samples = negative_samples
        return True

    @staticmethod
    def _normalize(frame: np.ndarray) -> np.ndarray:
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        return cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8)).apply(gray)

    def process(
        self,
        frame: np.ndarray,
        search_region: Rectangle | None = None,
    ) -> tuple[np.ndarray, AlignmentMeasurement | None, str]:
        with self._lock:
            zones = list(self._zones)
            negative_samples = [list(samples) for samples in self._negative_samples]
        annotated = frame.copy()
        if zones[0] is None:
            with self._lock:
                self._last_detection_counts = (0, 0)
                self._last_numbered_core_centers = []
            cv2.putText(annotated, "Teach a PCB core", (12, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 255), 2)
            return annotated, None, "Teach one PCB core example."

        frame_height, frame_width = frame.shape[:2]
        if search_region is None:
            search_left, search_top = 0, 0
            search_right, search_bottom = frame_width, frame_height
        else:
            search_left = max(0, search_region.x)
            search_top = max(0, search_region.y)
            search_right = min(frame_width, search_region.x + search_region.width)
            search_bottom = min(frame_height, search_region.y + search_region.height)
            if search_right <= search_left or search_bottom <= search_top:
                search_left, search_top = 0, 0
                search_right, search_bottom = frame_width, frame_height
        search_frame = frame[search_top:search_bottom, search_left:search_right]
        gray = self._normalize(search_frame)
        detected_by_type: list[list[tuple[Rectangle, float]]] = [[], []]
        for type_index, zone in enumerate(zones):
            if zone is None:
                continue
            candidates: list[tuple[Rectangle, float]] = []
            for sample in zone.samples:
                if gray.shape[0] < sample.template.shape[0] or gray.shape[1] < sample.template.shape[1]:
                    continue
                result = cv2.matchTemplate(gray, sample.template, cv2.TM_CCOEFF_NORMED)
                candidates.extend(
                    self._top_candidates(
                        result,
                        sample,
                        zone.guide,
                        self._MAX_DETECTIONS_PER_SAMPLE,
                        search_left,
                        search_top,
                    )
                )
            detected_by_type[type_index] = [
                candidate
                for candidate in self._deduplicate_candidates(candidates)
                if not self._matches_negative(frame, candidate[0], negative_samples[type_index])
            ]

        board_detections = detected_by_type[1]
        core_detections = detected_by_type[0]
        board_detections = self._reading_order(board_detections)
        numbered_cores: list[tuple[int, int, Rectangle, float]] = []
        incomplete_boards = 0
        if zones[1] is not None:
            for board_number, (board, _) in enumerate(board_detections, start=1):
                inside = [detection for detection in core_detections if self._contains(board, detection[0].center)]
                strongest_two = sorted(inside, key=lambda detection: detection[1], reverse=True)[:2]
                ordered_two = self._reading_order(strongest_two)
                if len(ordered_two) != 2:
                    incomplete_boards += 1
                for core_number, (core, score) in enumerate(ordered_two, start=1):
                    numbered_cores.append((board_number, core_number, core, score))
        else:
            for core_number, (core, score) in enumerate(self._reading_order(core_detections), start=1):
                numbered_cores.append((0, core_number, core, score))

        for board_number, (board, _) in enumerate(board_detections, start=1):
            board_core_count = sum(1 for pcb_number, _, _, _ in numbered_cores if pcb_number == board_number)
            color = (255, 80, 0) if board_core_count == 2 else (0, 0, 255)
            cv2.rectangle(annotated, (board.x, board.y), (board.x + board.width, board.y + board.height), color, 3)
            cv2.putText(annotated, f"PCB {board_number} ({board_core_count}/2)", (board.x, max(18, board.y - 6)), cv2.FONT_HERSHEY_SIMPLEX, 0.6, color, 2)

        if not numbered_cores:
            with self._lock:
                self._last_detection_counts = (len(board_detections), 0)
                self._last_numbered_core_centers = []
            board_status = f" Detected PCBs: {len(board_detections)}." if zones[1] is not None else ""
            return annotated, None, f"No taught PCB cores detected.{board_status}"

        for pcb_number, core_number, match, score in numbered_cores:
            color = (0, 255, 0)
            cv2.rectangle(annotated, (match.x, match.y), (match.x + match.width, match.y + match.height), color, 2)
            label = f"PCB {pcb_number} Core {core_number}" if pcb_number else f"Core {core_number}"
            cv2.putText(annotated, label, (match.x, max(16, match.y - 5)), cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 2)

        height, width = frame.shape[:2]
        primary_core = next(
            (match for pcb_number, core_number, match, _ in numbered_cores if pcb_number == 1 and core_number == 1),
            numbered_cores[0][2],
        )
        calibration_core = primary_core
        calibration_board_number = 1
        if board_detections:
            calibration_board_number = min(
                range(1, len(board_detections) + 1),
                key=lambda number: (
                    board_detections[number - 1][0].center[0] - width / 2.0
                ) ** 2
                + (
                    board_detections[number - 1][0].center[1] - height / 2.0
                ) ** 2,
            )
            calibration_core = next(
                (
                    match
                    for pcb_number, core_number, match, _ in numbered_cores
                    if pcb_number == calibration_board_number and core_number == 1
                ),
                primary_core,
            )
        detected_x, detected_y = calibration_core.center
        cv2.circle(annotated, (round(detected_x), round(detected_y)), 7, (255, 0, 255), 2)
        cv2.putText(annotated, "TRACK", (round(detected_x) + 9, round(detected_y) - 9), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 0, 255), 2)
        measurement = AlignmentMeasurement(
            detected_x,
            detected_y,
            width / 2.0 - detected_x,
            height / 2.0 - detected_y,
            max(score for _, _, _, score in numbered_cores),
            max((score for _, score in board_detections), default=0.0),
            primary_core.center[0],
            primary_core.center[1],
        )
        detected_core_count = len(numbered_cores)
        cv2.putText(annotated, f"PCBs: {len(board_detections)}  Cores: {detected_core_count}  Incomplete: {incomplete_boards}", (12, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.65, (0, 255, 0), 2)
        with self._lock:
            self._last_detection_counts = (len(board_detections), detected_core_count)
            self._last_numbered_core_centers = [
                (pcb_number, core_number, match.center[0], match.center[1])
                for pcb_number, core_number, match, _ in numbered_cores
            ]
        return annotated, measurement, f"Detected {len(board_detections)} PCBs and {detected_core_count} cores; visual tracking reference is PCB {calibration_board_number} Core 1; {incomplete_boards} PCBs are incomplete."

    @staticmethod
    def _contains(rectangle: Rectangle, point: tuple[float, float]) -> bool:
        return rectangle.x <= point[0] <= rectangle.x + rectangle.width and rectangle.y <= point[1] <= rectangle.y + rectangle.height

    @staticmethod
    def _reading_order(detections: list[tuple[Rectangle, float]]) -> list[tuple[Rectangle, float]]:
        """Number detections top-to-bottom and left-to-right within each visual row."""
        if not detections:
            return []
        typical_height = sorted(rectangle.height for rectangle, _ in detections)[len(detections) // 2]
        row_height = max(1.0, typical_height * 0.6)
        return sorted(detections, key=lambda detection: (round(detection[0].center[1] / row_height), detection[0].center[0]))

    def _matches_negative(self, frame: np.ndarray, rectangle: Rectangle, negatives: list[np.ndarray]) -> bool:
        if not negatives:
            return False
        height, width = frame.shape[:2]
        left, top = max(0, rectangle.x), max(0, rectangle.y)
        right, bottom = min(width, rectangle.x + rectangle.width), min(height, rectangle.y + rectangle.height)
        if right <= left or bottom <= top:
            return True
        candidate = self._normalize(frame[top:bottom, left:right])
        for negative in negatives:
            resized = cv2.resize(candidate, (negative.shape[1], negative.shape[0]))
            score = float(cv2.matchTemplate(resized, negative, cv2.TM_CCOEFF_NORMED)[0, 0])
            if score >= 0.72:
                return True
        return False

    @staticmethod
    def _deduplicate_candidates(candidates: list[tuple[Rectangle, float]]) -> list[tuple[Rectangle, float]]:
        kept: list[tuple[Rectangle, float]] = []
        for rectangle, score in sorted(candidates, key=lambda candidate: candidate[1], reverse=True):
            minimum_distance = max(8.0, min(rectangle.width, rectangle.height) * 0.6)
            if any(
                (rectangle.center[0] - existing.center[0]) ** 2 + (rectangle.center[1] - existing.center[1]) ** 2
                < minimum_distance ** 2
                for existing, _ in kept
            ):
                continue
            kept.append((rectangle, score))
        return kept

    @staticmethod
    def _top_candidates(
        result: np.ndarray,
        sample: ZoneSample,
        guide: Rectangle,
        count: int = 8,
        origin_x: int = 0,
        origin_y: int = 0,
    ) -> list[tuple[Rectangle, float]]:
        working = result.copy()
        candidates: list[tuple[Rectangle, float]] = []
        suppression = max(12, min(sample.template.shape) // 2)
        for _ in range(count):
            _, score, _, location = cv2.minMaxLoc(working)
            if score < PrintZoneAligner._MIN_SCORE:
                break
            candidates.append(
                (
                    Rectangle(
                        origin_x + location[0] + sample.target_offset_x,
                        origin_y + location[1] + sample.target_offset_y,
                        guide.width,
                        guide.height,
                    ),
                    float(score),
                )
            )
            cv2.rectangle(working, (max(0, location[0] - suppression), max(0, location[1] - suppression)), (min(working.shape[1] - 1, location[0] + suppression), min(working.shape[0] - 1, location[1] + suppression)), -1.0, -1)
        return candidates
