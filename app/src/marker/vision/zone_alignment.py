"""Template-based alignment for two PCB print zones."""

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


@dataclass(frozen=True)
class LearnedZone:
    """A print target plus the larger visual context used to locate it."""

    guide: Rectangle
    template: np.ndarray
    target_offset_x: int
    target_offset_y: int


class PrintZoneAligner:
    """Learns two visual templates and compares them to fixed screen guides."""

    _MIN_SCORE = 0.52
    _CONTEXT_PADDING_PX = 40
    _MAX_PAIR_SHIFT_DIFFERENCE_PX = 16.0

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._zones: list[LearnedZone | None] = [None, None]

    def teach(self, index: int, frame: np.ndarray, rectangle: Rectangle) -> None:
        if index not in (0, 1):
            raise ValueError("Zone index must be 0 or 1")
        if rectangle.width < 12 or rectangle.height < 12:
            raise ValueError("Select a larger print zone")

        height, width = frame.shape[:2]
        if rectangle.x < 0 or rectangle.y < 0 or rectangle.x + rectangle.width > width or rectangle.y + rectangle.height > height:
            raise ValueError("Selected zone is outside the camera frame")

        left = max(0, rectangle.x - self._CONTEXT_PADDING_PX)
        top = max(0, rectangle.y - self._CONTEXT_PADDING_PX)
        right = min(width, rectangle.x + rectangle.width + self._CONTEXT_PADDING_PX)
        bottom = min(height, rectangle.y + rectangle.height + self._CONTEXT_PADDING_PX)
        template = self._normalize(frame[top:bottom, left:right])
        zone = LearnedZone(
            guide=rectangle,
            template=template,
            target_offset_x=rectangle.x - left,
            target_offset_y=rectangle.y - top,
        )
        with self._lock:
            self._zones[index] = zone

    def clear(self) -> None:
        with self._lock:
            self._zones = [None, None]

    def save(self, path: Path) -> None:
        """Persist taught targets for a fixed camera and fixture."""
        with self._lock:
            if any(zone is None for zone in self._zones):
                return
            zones = [zone for zone in self._zones if zone is not None]
        path.parent.mkdir(parents=True, exist_ok=True)
        np.savez_compressed(
            path,
            template_0=zones[0].template,
            template_1=zones[1].template,
            guide_0=np.array([zones[0].guide.x, zones[0].guide.y, zones[0].guide.width, zones[0].guide.height]),
            guide_1=np.array([zones[1].guide.x, zones[1].guide.y, zones[1].guide.width, zones[1].guide.height]),
            offset_0=np.array([zones[0].target_offset_x, zones[0].target_offset_y]),
            offset_1=np.array([zones[1].target_offset_x, zones[1].target_offset_y]),
        )

    def load(self, path: Path) -> bool:
        """Load previously taught targets, returning False if none are available."""
        if not path.exists():
            return False
        try:
            with np.load(path, allow_pickle=False) as data:
                zones = []
                for index in (0, 1):
                    guide_values = [int(value) for value in data[f"guide_{index}"]]
                    offset_values = [int(value) for value in data[f"offset_{index}"]]
                    zones.append(
                        LearnedZone(
                            guide=Rectangle(*guide_values),
                            template=data[f"template_{index}"].copy(),
                            target_offset_x=offset_values[0],
                            target_offset_y=offset_values[1],
                        )
                    )
        except (KeyError, OSError, ValueError):
            return False
        with self._lock:
            self._zones = zones
        return True

    @staticmethod
    def _normalize(frame: np.ndarray) -> np.ndarray:
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        return cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8)).apply(gray)

    def process(self, frame: np.ndarray) -> tuple[np.ndarray, AlignmentMeasurement | None, str]:
        with self._lock:
            zones = list(self._zones)

        annotated = frame.copy()
        if any(zone is None for zone in zones):
            cv2.putText(annotated, "Teach Zone 1 and Zone 2", (12, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 255), 2)
            return annotated, None, "Teach both 11 x 5 mm print targets; surrounding visual context is captured automatically."

        gray = self._normalize(frame)
        candidate_sets: list[list[tuple[Rectangle, float]]] = []
        guides: list[Rectangle] = []
        for zone in zones:
            assert zone is not None
            result = cv2.matchTemplate(gray, zone.template, cv2.TM_CCOEFF_NORMED)
            candidate_sets.append(self._top_candidates(result, zone))
            guides.append(zone.guide)

        matches = self._select_consistent_pair(candidate_sets[0], candidate_sets[1], guides)
        if matches is None:
            return annotated, None, "Print-zone matches disagree. Keep the camera fixed or reteach the zones."

        for (match, score), zone in zip(matches, zones):
            assert zone is not None
            cv2.rectangle(
                annotated,
                (zone.guide.x, zone.guide.y),
                (zone.guide.x + zone.guide.width, zone.guide.y + zone.guide.height),
                (0, 0, 255),
                2,
            )
            color = (0, 255, 0) if score >= self._MIN_SCORE else (0, 165, 255)
            cv2.rectangle(
                annotated,
                (match.x, match.y),
                (match.x + match.width, match.y + match.height),
                color,
                2,
            )

        if any(score < self._MIN_SCORE for _, score in matches):
            return annotated, None, "Print-zone match is weak. Improve lighting or reteach the zones."

        detected_x = sum(match.center[0] for match, _ in matches) / 2.0
        detected_y = sum(match.center[1] for match, _ in matches) / 2.0
        guide_x = sum(guide.center[0] for guide in guides) / 2.0
        guide_y = sum(guide.center[1] for guide in guides) / 2.0
        measurement = AlignmentMeasurement(
            midpoint_x=detected_x,
            midpoint_y=detected_y,
            error_x=guide_x - detected_x,
            error_y=guide_y - detected_y,
            score_1=matches[0][1],
            score_2=matches[1][1],
        )
        cv2.putText(
            annotated,
            f"Zone error: X {measurement.error_x:+.1f}px  Y {measurement.error_y:+.1f}px",
            (12, 30),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.65,
            (0, 255, 0),
            2,
        )
        return annotated, measurement, "Print zones detected"

    @staticmethod
    def _top_candidates(result: np.ndarray, zone: LearnedZone, count: int = 8) -> list[tuple[Rectangle, float]]:
        """Return spatially distinct likely matches rather than only one peak."""
        working = result.copy()
        candidates: list[tuple[Rectangle, float]] = []
        suppression = max(12, min(zone.template.shape) // 2)
        for _ in range(count):
            _, score, _, location = cv2.minMaxLoc(working)
            if score < PrintZoneAligner._MIN_SCORE:
                break
            match = Rectangle(
                location[0] + zone.target_offset_x,
                location[1] + zone.target_offset_y,
                zone.guide.width,
                zone.guide.height,
            )
            candidates.append((match, float(score)))
            cv2.rectangle(
                working,
                (max(0, location[0] - suppression), max(0, location[1] - suppression)),
                (min(working.shape[1] - 1, location[0] + suppression), min(working.shape[0] - 1, location[1] + suppression)),
                -1.0,
                -1,
            )
        return candidates

    def _select_consistent_pair(
        self,
        first: list[tuple[Rectangle, float]],
        second: list[tuple[Rectangle, float]],
        guides: list[Rectangle],
    ) -> list[tuple[Rectangle, float]] | None:
        best: tuple[float, list[tuple[Rectangle, float]]] | None = None
        for match_1, score_1 in first:
            shift_1 = (match_1.x - guides[0].x, match_1.y - guides[0].y)
            for match_2, score_2 in second:
                shift_2 = (match_2.x - guides[1].x, match_2.y - guides[1].y)
                disagreement = float(np.hypot(shift_1[0] - shift_2[0], shift_1[1] - shift_2[1]))
                if disagreement > self._MAX_PAIR_SHIFT_DIFFERENCE_PX:
                    continue
                quality = score_1 + score_2 - (disagreement / self._MAX_PAIR_SHIFT_DIFFERENCE_PX)
                if best is None or quality > best[0]:
                    best = (quality, [(match_1, score_1), (match_2, score_2)])
        return best[1] if best else None
