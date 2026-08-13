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


class PrintZoneAligner:
    """Learns two visual templates and compares them to fixed screen guides."""

    _MIN_SCORE = 0.70

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._templates: list[np.ndarray | None] = [None, None]
        self._guides: list[Rectangle | None] = [None, None]

    def teach(self, index: int, frame: np.ndarray, rectangle: Rectangle) -> None:
        if index not in (0, 1):
            raise ValueError("Zone index must be 0 or 1")
        if rectangle.width < 12 or rectangle.height < 12:
            raise ValueError("Select a larger print zone")

        height, width = frame.shape[:2]
        if rectangle.x < 0 or rectangle.y < 0 or rectangle.x + rectangle.width > width or rectangle.y + rectangle.height > height:
            raise ValueError("Selected zone is outside the camera frame")

        template = cv2.cvtColor(
            frame[rectangle.y : rectangle.y + rectangle.height, rectangle.x : rectangle.x + rectangle.width],
            cv2.COLOR_BGR2GRAY,
        ).copy()
        with self._lock:
            self._templates[index] = template
            self._guides[index] = rectangle

    def clear(self) -> None:
        with self._lock:
            self._templates = [None, None]
            self._guides = [None, None]

    def process(self, frame: np.ndarray) -> tuple[np.ndarray, AlignmentMeasurement | None, str]:
        with self._lock:
            templates = list(self._templates)
            guides = list(self._guides)

        annotated = frame.copy()
        if any(template is None for template in templates):
            cv2.putText(annotated, "Teach Zone 1 and Zone 2", (12, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 255), 2)
            return annotated, None, "Teach both print zones by dragging red rectangles over them."

        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        matches: list[tuple[Rectangle, float]] = []
        for template, guide in zip(templates, guides):
            assert template is not None
            assert guide is not None
            result = cv2.matchTemplate(gray, template, cv2.TM_CCOEFF_NORMED)
            _, score, _, location = cv2.minMaxLoc(result)
            match = Rectangle(location[0], location[1], template.shape[1], template.shape[0])
            matches.append((match, float(score)))
            cv2.rectangle(
                annotated,
                (guide.x, guide.y),
                (guide.x + guide.width, guide.y + guide.height),
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
        guide_x = sum(guide.center[0] for guide in guides if guide is not None) / 2.0
        guide_y = sum(guide.center[1] for guide in guides if guide is not None) / 2.0
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
