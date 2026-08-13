"""Detection and geometry helpers for circular PCB fiducials."""

from __future__ import annotations

from dataclasses import dataclass
from math import atan2, degrees

import cv2
import numpy as np


@dataclass(frozen=True)
class Fiducial:
    x: float
    y: float
    radius: float


@dataclass(frozen=True)
class FiducialPair:
    left: Fiducial
    right: Fiducial

    @property
    def midpoint(self) -> tuple[float, float]:
        return ((self.left.x + self.right.x) / 2.0, (self.left.y + self.right.y) / 2.0)

    @property
    def angle_degrees(self) -> float:
        return degrees(atan2(self.right.y - self.left.y, self.right.x - self.left.x))


def detect_fiducial_pair(frame: np.ndarray) -> FiducialPair | None:
    """Find the two largest circular candidates in a camera frame.

    This is an inspection-only first pass. Machine movement must remain manual
    until the result has been calibrated and validated on production panels.
    """
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    blurred = cv2.medianBlur(gray, 5)
    height, width = gray.shape
    circles = cv2.HoughCircles(
        blurred,
        cv2.HOUGH_GRADIENT,
        dp=1.2,
        minDist=max(24, min(width, height) // 8),
        param1=100,
        param2=18,
        minRadius=max(3, min(width, height) // 100),
        maxRadius=max(8, min(width, height) // 4),
    )
    if circles is None or len(circles[0]) < 2:
        return None

    candidates = [Fiducial(float(x), float(y), float(radius)) for x, y, radius in circles[0]]
    candidates.sort(key=lambda candidate: candidate.radius, reverse=True)
    first, second = candidates[:2]
    left, right = sorted((first, second), key=lambda candidate: candidate.x)
    return FiducialPair(left=left, right=right)


def draw_fiducial_overlay(frame: np.ndarray, pair: FiducialPair | None) -> np.ndarray:
    """Return a copy of a camera frame annotated with the detected geometry."""
    overlay = frame.copy()
    if pair is None:
        cv2.putText(overlay, "Fiducials: searching", (12, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 165, 255), 2)
        return overlay

    for label, fiducial in (("F1", pair.left), ("F2", pair.right)):
        center = (round(fiducial.x), round(fiducial.y))
        cv2.circle(overlay, center, round(fiducial.radius), (0, 255, 0), 2)
        cv2.circle(overlay, center, 2, (0, 255, 0), 3)
        cv2.putText(overlay, label, (center[0] + 8, center[1] - 8), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2)

    midpoint = pair.midpoint
    midpoint_int = (round(midpoint[0]), round(midpoint[1]))
    cv2.line(overlay, (round(pair.left.x), round(pair.left.y)), (round(pair.right.x), round(pair.right.y)), (0, 255, 0), 1)
    cv2.drawMarker(overlay, midpoint_int, (0, 165, 255), cv2.MARKER_CROSS, 18, 2)
    cv2.putText(
        overlay,
        f"Midpoint: {midpoint[0]:.0f}, {midpoint[1]:.0f} px  Angle: {pair.angle_degrees:.2f} deg",
        (12, 30),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.6,
        (0, 255, 0),
        2,
    )
    return overlay
