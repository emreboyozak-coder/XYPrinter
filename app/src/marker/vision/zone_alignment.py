"""Template-based alignment for two PCB print zones."""

from __future__ import annotations

import threading
from dataclasses import dataclass

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

    _MIN_SCORE = 0.70
    _CONTEXT_PADDING_PX = 40

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
        matches: list[tuple[Rectangle, float]] = []
        guides: list[Rectangle] = []
        for zone in zones:
            assert zone is not None
            result = cv2.matchTemplate(gray, zone.template, cv2.TM_CCOEFF_NORMED)
            _, score, _, location = cv2.minMaxLoc(result)
            match = Rectangle(
                location[0] + zone.target_offset_x,
                location[1] + zone.target_offset_y,
                zone.guide.width,
                zone.guide.height,
            )
            matches.append((match, float(score)))
            guides.append(zone.guide)
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
