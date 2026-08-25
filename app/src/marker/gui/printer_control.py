"""Desktop motion control with repeated PCB core detection."""

from __future__ import annotations

import logging
import os
import sys
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

import cv2
import numpy as np
from PyQt5 import QtWidgets
from PyQt5.QtCore import QPoint, QRect, QSize, Qt, QThread, QTimer, pyqtSignal
from PyQt5.QtGui import QFont, QImage, QPainter, QPen, QPixmap
from PyQt5.QtWidgets import (
    QComboBox,
    QDoubleSpinBox,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from marker.motion.controller import MotionController, discover_ports
from marker.vision.zone_alignment import AlignmentMeasurement, PrintZoneAligner, Rectangle

logger = logging.getLogger(__name__)


def configure_opencv_hardware() -> tuple[int, bool]:
    """Enable OpenCV acceleration while leaving one CPU thread for the UI/camera."""
    logical_cpus = os.cpu_count() or 2
    default_threads = max(1, logical_cpus - 1)
    configured_threads = os.environ.get("PCB_PRINTER_CV_THREADS", "").strip()
    try:
        thread_count = max(1, int(configured_threads)) if configured_threads else default_threads
    except ValueError:
        logger.warning(
            "Ignoring invalid PCB_PRINTER_CV_THREADS=%r; using %d threads",
            configured_threads,
            default_threads,
        )
        thread_count = default_threads

    cv2.setUseOptimized(True)
    cv2.setNumThreads(thread_count)

    opencl_enabled = False
    if hasattr(cv2, "ocl") and cv2.ocl.haveOpenCL():
        cv2.ocl.setUseOpenCL(True)
        opencl_enabled = bool(cv2.ocl.useOpenCL())

    logger.info(
        "OpenCV hardware acceleration: optimized=%s, CPU threads=%d/%d, OpenCL=%s",
        cv2.useOptimized(),
        cv2.getNumThreads(),
        logical_cpus,
        opencl_enabled,
    )
    return cv2.getNumThreads(), opencl_enabled


class CameraPreview(QLabel):
    """Aspect-ratio-safe preview that lets an operator teach template rectangles."""

    selection_made = pyqtSignal(int, int, int, int)

    def __init__(self) -> None:
        super().__init__()
        self._frame_size = QSize()
        self._selection_enabled = False
        self._drag_start: Optional[QPoint] = None
        self._drag_end: Optional[QPoint] = None

    def show_image(self, image: QImage) -> None:
        self._frame_size = image.size()
        pixmap = QPixmap.fromImage(image).scaled(self.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation)
        self.setPixmap(pixmap)

    def set_selection_enabled(self, enabled: bool) -> None:
        self._selection_enabled = enabled
        self.setCursor(Qt.CrossCursor if enabled else Qt.ArrowCursor)

    def clear_selection(self) -> None:
        self._drag_start = None
        self._drag_end = None
        self.update()

    def _visible_rect(self) -> QRect:
        if self._frame_size.isEmpty():
            return QRect()
        scale = min(self.width() / self._frame_size.width(), self.height() / self._frame_size.height())
        width = round(self._frame_size.width() * scale)
        height = round(self._frame_size.height() * scale)
        return QRect((self.width() - width) // 2, (self.height() - height) // 2, width, height)

    def _to_frame_point(self, point: QPoint) -> Optional[QPoint]:
        visible = self._visible_rect()
        if visible.isEmpty() or not visible.contains(point):
            return None
        x = round((point.x() - visible.x()) * self._frame_size.width() / visible.width())
        y = round((point.y() - visible.y()) * self._frame_size.height() / visible.height())
        return QPoint(max(0, min(x, self._frame_size.width() - 1)), max(0, min(y, self._frame_size.height() - 1)))

    def mousePressEvent(self, event) -> None:  # type: ignore[no-untyped-def]
        if self._selection_enabled and event.button() == Qt.LeftButton:
            point = self._to_frame_point(event.pos())
            if point:
                self._drag_start = point
                self._drag_end = point
                self.update()
                return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:  # type: ignore[no-untyped-def]
        if self._drag_start:
            point = self._to_frame_point(event.pos())
            if point:
                self._drag_end = point
                self.update()
                return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:  # type: ignore[no-untyped-def]
        if self._drag_start and event.button() == Qt.LeftButton:
            point = self._to_frame_point(event.pos())
            start, end = self._drag_start, point or self._drag_end
            self._drag_end = end
            self.set_selection_enabled(False)
            self.update()
            if end:
                x1, x2 = sorted((start.x(), end.x()))
                y1, y2 = sorted((start.y(), end.y()))
                self.selection_made.emit(x1, y1, x2 - x1 + 1, y2 - y1 + 1)
                return
        super().mouseReleaseEvent(event)

    def paintEvent(self, event) -> None:  # type: ignore[no-untyped-def]
        super().paintEvent(event)
        if not self._drag_start or not self._drag_end or self._frame_size.isEmpty():
            return
        visible = self._visible_rect()
        scale_x = visible.width() / self._frame_size.width()
        scale_y = visible.height() / self._frame_size.height()
        start = QPoint(visible.x() + round(self._drag_start.x() * scale_x), visible.y() + round(self._drag_start.y() * scale_y))
        end = QPoint(visible.x() + round(self._drag_end.x() * scale_x), visible.y() + round(self._drag_end.y() * scale_y))
        painter = QPainter(self)
        painter.setPen(QPen(Qt.red, 2))
        painter.drawRect(QRect(start, end).normalized())


class MotionThread(QThread):
    """Runs one blocking firmware move without freezing the window."""

    motion_complete = pyqtSignal(float, float)
    motion_error = pyqtSignal(str)

    def __init__(self, controller: MotionController) -> None:
        super().__init__()
        self.controller = controller
        self.target_x = 0.0
        self.target_y = 0.0
        self.speed = 20.0
        self.timeout_s = 20.0

    def set_target(self, x: float, y: float, speed: float, timeout_s: float) -> None:
        self.target_x, self.target_y, self.speed, self.timeout_s = x, y, speed, timeout_s

    def run(self) -> None:
        try:
            self.controller.move_to(self.target_x, self.target_y, self.speed, self.timeout_s)
            self.motion_complete.emit(self.target_x, self.target_y)
        except Exception as exc:
            self.motion_error.emit(str(exc))


class CameraThread(QThread):
    """Drains DroidCam continuously and analyzes only the newest available frame."""

    ANALYSIS_INTERVAL_S = 0.2
    TARGET_SEARCH_SCALES = (0.50, 0.75, 1.0)

    frame_ready = pyqtSignal(int, QImage)
    connection_changed = pyqtSignal(int, bool, str)
    alignment_measurement_changed = pyqtSignal(int, float, float, float, float, float, float, float, float, float, float)
    alignment_status_changed = pyqtSignal(int, str)
    detection_counts_changed = pyqtSignal(int, int, int)

    def __init__(self, session: int, ip: str, port: int, template_path: Path) -> None:
        super().__init__()
        self.session = session
        self.url = f"http://{ip}:{port}/video"
        self.template_path = template_path
        self._running = True
        self._frame_lock = threading.Lock()
        self._latest_frame: Optional[object] = None
        self._latest_frame_serial = 0
        self._last_processed_frame: Optional[object] = None
        self._last_processed_measurement: Optional[AlignmentMeasurement] = None
        self._last_processed_counts = (0, 0)
        self._last_processed_core_targets: list[tuple[int, int, float, float]] = []
        self._frame_available = threading.Event()
        self.aligner = PrintZoneAligner()
        self.loaded_saved_zones = self.aligner.load(template_path)
        self._last_status = ""
        self._target_search_enabled = False
        self._target_search_level = 0
        self._analysis_enabled = False
        self._freeze_display = False
        self._analysis_lock = threading.Lock()

    def stop(self) -> None:
        self._running = False
        self._frame_available.set()

    def set_target_search_enabled(self, enabled: bool) -> None:
        """Use a center-focused search during core navigation, with full-frame fallback."""
        self._target_search_enabled = enabled
        self._target_search_level = 0

    def start_panel_scan(self) -> None:
        """Enable detection until the GUI accepts and locks a complete panel."""
        with self._analysis_lock:
            self._analysis_enabled = True
            self._freeze_display = False
        self._target_search_enabled = False
        self._target_search_level = 0
        self._frame_available.set()

    def stop_image_processing(self, *, freeze_display: bool) -> None:
        """Stop PCB/core detection while optionally keeping the accepted overlay visible."""
        with self._analysis_lock:
            self._analysis_enabled = False
            self._freeze_display = freeze_display
        self._frame_available.set()

    def _target_search_region(self, frame: object) -> Optional[Rectangle]:
        if not self._target_search_enabled:
            return None
        height, width = frame.shape[:2]  # type: ignore[attr-defined]
        scale = self.TARGET_SEARCH_SCALES[self._target_search_level]
        if scale >= 1.0:
            return None
        region_width = max(1, round(width * scale))
        region_height = max(1, round(height * scale))
        return Rectangle(
            (width - region_width) // 2,
            (height - region_height) // 2,
            region_width,
            region_height,
        )

    def teach_zone(self, index: int, rectangle: Rectangle, append: bool) -> None:
        with self._frame_lock:
            if self._latest_frame is None:
                raise RuntimeError("No camera frame is available")
            frame = self._latest_frame.copy()
        self.aligner.teach(index, frame, rectangle, append=append)
        self.aligner.save(self.template_path)

    def latest_frame_copy(self):  # type: ignore[no-untyped-def]
        with self._frame_lock:
            if self._latest_frame is None:
                raise RuntimeError("No camera frame is available")
            return self._latest_frame.copy()

    def teach_negative(self, index: int, rectangle: Rectangle) -> None:
        with self._frame_lock:
            if self._latest_frame is None:
                raise RuntimeError("No camera frame is available")
            frame = self._latest_frame.copy()
        self.aligner.teach_negative(index, frame, rectangle)
        self.aligner.save(self.template_path)

    def clear_zones(self) -> None:
        self.aligner.clear()
        self.template_path.unlink(missing_ok=True)

    def clear_learning_type(self, index: int) -> None:
        self.aligner.clear_type(index)
        if self.aligner.sample_counts() == (0, 0):
            self.template_path.unlink(missing_ok=True)
        else:
            self.aligner.save(self.template_path)

    def save_latest_frame(self, path: Path, x: float, y: float) -> tuple[int, int, Optional[float], Optional[float], list[tuple[int, int, float, float]]]:
        with self._frame_lock:
            if self._last_processed_frame is None:
                raise RuntimeError("No analyzed panel frame is available")
            frame = self._last_processed_frame.copy()
            measurement = self._last_processed_measurement
            counts = self._last_processed_counts
            core_targets = list(self._last_processed_core_targets)
        cv2.putText(
            frame,
            f"Position X={x:.3f} mm  Y={y:.3f} mm",
            (12, frame.shape[0] - 18),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.7,
            (0, 255, 255),
            2,
        )
        path.parent.mkdir(parents=True, exist_ok=True)
        if not cv2.imwrite(str(path), frame):
            raise RuntimeError(f"Could not write snapshot: {path}")
        primary_x = measurement.primary_x if measurement is not None else None
        primary_y = measurement.primary_y if measurement is not None else None
        return counts[0], counts[1], primary_x, primary_y, core_targets

    def _emit_status(self, status: str) -> None:
        if status != self._last_status:
            self._last_status = status
            self.alignment_status_changed.emit(self.session, status)

    def run(self) -> None:
        camera = cv2.VideoCapture()
        camera.set(cv2.CAP_PROP_OPEN_TIMEOUT_MSEC, 3000)
        camera.set(cv2.CAP_PROP_READ_TIMEOUT_MSEC, 3000)
        camera.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        opened = camera.open(self.url, cv2.CAP_FFMPEG)
        if not opened:
            camera.release()
            self.connection_changed.emit(self.session, False, f"Camera connection failed: {self.url}")
            return
        ok, frame = camera.read()
        if not ok or frame is None:
            camera.release()
            self.connection_changed.emit(self.session, False, f"Camera stream did not return a frame: {self.url}")
            return

        camera.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        with self._frame_lock:
            self._latest_frame = frame.copy()
            self._latest_frame_serial += 1
        self._frame_available.set()
        self.connection_changed.emit(self.session, True, f"Camera connected: {self.url}")
        capture_thread = threading.Thread(target=self._capture_latest_frames, args=(camera,), daemon=True)
        capture_thread.start()
        processed_serial = -1
        next_analysis_at = 0.0
        while self._running:
            self._frame_available.wait(timeout=0.25)
            self._frame_available.clear()
            with self._analysis_lock:
                analysis_enabled = self._analysis_enabled
                freeze_display = self._freeze_display
            if freeze_display:
                continue
            delay = next_analysis_at - time.monotonic()
            if delay > 0:
                time.sleep(delay)
            with self._frame_lock:
                if self._latest_frame is None or self._latest_frame_serial == processed_serial:
                    continue
                frame = self._latest_frame.copy()
                processed_serial = self._latest_frame_serial
            next_analysis_at = time.monotonic() + self.ANALYSIS_INTERVAL_S
            search_region = self._target_search_region(frame) if analysis_enabled else None
            if analysis_enabled:
                display_frame, measurement, status = self.aligner.process(frame, search_region)
            else:
                display_frame = frame
                measurement = None
                status = "Panel scan is idle. Press Panel Scan to detect 20 PCBs and 40 cores."
            if analysis_enabled and self._target_search_enabled:
                if measurement is None:
                    self._target_search_level = min(
                        self._target_search_level + 1,
                        len(self.TARGET_SEARCH_SCALES) - 1,
                    )
                else:
                    self._target_search_level = 0
                if search_region is not None:
                    cv2.rectangle(
                        display_frame,
                        (search_region.x, search_region.y),
                        (search_region.x + search_region.width, search_region.y + search_region.height),
                        (0, 165, 255),
                        2,
                    )
            if analysis_enabled:
                pcb_count, core_count = self.aligner.detection_counts()
                with self._frame_lock:
                    self._last_processed_frame = display_frame.copy()
                    self._last_processed_measurement = measurement
                    self._last_processed_counts = (pcb_count, core_count)
                    self._last_processed_core_targets = self.aligner.numbered_core_centers()
                self.detection_counts_changed.emit(self.session, pcb_count, core_count)
            frame_height, frame_width = display_frame.shape[:2]
            center_x = frame_width // 2
            center_y = frame_height // 2
            cv2.line(display_frame, (0, center_y), (frame_width - 1, center_y), (255, 255, 0), 2)
            cv2.line(display_frame, (center_x, 0), (center_x, frame_height - 1), (255, 255, 0), 2)
            self._emit_status(status)
            if measurement:
                self.alignment_measurement_changed.emit(
                    self.session,
                    measurement.midpoint_x,
                    measurement.midpoint_y,
                    measurement.error_x,
                    measurement.error_y,
                    measurement.score_1,
                    measurement.score_2,
                    float(center_x),
                    float(center_y),
                    float(measurement.primary_x if measurement.primary_x is not None else measurement.midpoint_x),
                    float(measurement.primary_y if measurement.primary_y is not None else measurement.midpoint_y),
                )

            rgb = cv2.cvtColor(display_frame, cv2.COLOR_BGR2RGB)
            height, width, channels = rgb.shape
            self.frame_ready.emit(self.session, QImage(rgb.data, width, height, channels * width, QImage.Format_RGB888).copy())
        self._running = False
        capture_thread.join(timeout=4.0)
        camera.release()

    def _capture_latest_frames(self, camera: cv2.VideoCapture) -> None:
        """Continuously drain DroidCam so analysis never works through stale buffered frames."""
        while self._running:
            ok, frame = camera.read()
            if not ok or frame is None:
                self._emit_status("Camera stream interrupted")
                self._running = False
                self._frame_available.set()
                return
            with self._frame_lock:
                self._latest_frame = frame.copy()
                self._latest_frame_serial += 1
            self._frame_available.set()
            time.sleep(0.001)


class PCBPrinterGUI(QMainWindow):
    """Control surface for verified motion plus supervised camera alignment."""

    CALIBRATION_DISTANCE_MM = 10.0
    MAX_AUTO_X_STEP_MM = 2.0
    CAMERA_SETTLE_DELAY_MS = 5_000
    TEMPLATE_PATH = Path(__file__).resolve().parents[4] / "config" / "print-zone-templates.npz"
    STARTUP_CAPTURE_DIR = Path(__file__).resolve().parents[4] / "snapshots"
    EXPECTED_PCB_COUNT = 20
    EXPECTED_CORE_COUNT = 40

    def __init__(self) -> None:
        super().__init__()
        logging.basicConfig(level=logging.INFO)
        configure_opencv_hardware()
        self.setWindowTitle("PCB Printer Motion and Vision Alignment")
        self.setMinimumSize(1050, 650)

        self.motion: Optional[MotionController] = None
        self.motion_thread: Optional[MotionThread] = None
        self.camera_thread: Optional[CameraThread] = None
        self._retired_camera_threads: list[CameraThread] = []
        self._camera_session = 0
        self.is_connected = False
        self.current_x = 0.0
        self.current_y = 0.0
        self.last_measurement: Optional[AlignmentMeasurement] = None
        self.pixels_per_mm_x: Optional[float] = None
        self.center_pixels_per_mm_x: Optional[float] = None
        self.x_axis_camera_response: Optional[tuple[float, float]] = None
        self.y_axis_camera_response: Optional[tuple[float, float]] = None
        self.camera_center_x: Optional[float] = None
        self.camera_center_y: Optional[float] = None
        self.detected_pcb_count = 0
        self.detected_core_count = 0
        self._full_layout_capture_saved = False
        self._panel_scan_active = False
        self._reference_primary_core: Optional[tuple[float, float]] = None
        self._reference_machine_position: Optional[tuple[float, float]] = None
        self._reference_core_targets: list[tuple[int, int, float, float]] = []
        self._current_core_target_index = 0
        self._core_navigation_ready = False
        self._navigation_target_label: Optional[str] = None
        self._auto_center_phase: Optional[str] = None
        self._auto_center_y_correction: Optional[float] = None
        self._teach_zone_request: Optional[tuple[int, bool]] = None
        self._reject_core_request: Optional[int] = None
        self._pending_calibration: Optional[tuple[float, float, float]] = None
        self._pending_y_calibration: Optional[tuple[float, float, float]] = None
        self._pending_calibration_frame: Optional[object] = None
        self._measurement_serial = 0
        self._calibration_wait_serial: Optional[int] = None

        self._build_ui()
        QTimer.singleShot(0, self.connect_camera)

    def _build_ui(self) -> None:
        central = QWidget()
        self.setCentralWidget(central)
        layout = QHBoxLayout(central)

        camera_layout = QVBoxLayout()
        camera_group = QGroupBox("DroidCam and Multi-Core Detection")
        camera_group_layout = QVBoxLayout(camera_group)
        self.camera_label = CameraPreview()
        self.camera_label.setText("Connecting to DroidCam...")
        self.camera_label.setAlignment(Qt.AlignCenter)
        self.camera_label.setMinimumSize(640, 480)
        self.camera_label.setStyleSheet("background: #171717; color: #f0f0f0;")
        self.camera_label.selection_made.connect(self.on_zone_selected)
        camera_group_layout.addWidget(self.camera_label)

        camera_connection = QGridLayout()
        camera_connection.addWidget(QLabel("WiFi IP"), 0, 0)
        self.camera_ip_input = QLineEdit("10.59.59.87")
        camera_connection.addWidget(self.camera_ip_input, 0, 1)
        camera_connection.addWidget(QLabel("Port"), 0, 2)
        self.camera_port_input = QSpinBox()
        self.camera_port_input.setRange(1, 65535)
        self.camera_port_input.setValue(4747)
        camera_connection.addWidget(self.camera_port_input, 0, 3)
        self.camera_connect_button = QPushButton("Connect Camera")
        self.camera_connect_button.clicked.connect(self.connect_camera)
        camera_connection.addWidget(self.camera_connect_button, 1, 1)
        self.camera_disconnect_button = QPushButton("Disconnect Camera")
        self.camera_disconnect_button.clicked.connect(self.disconnect_camera)
        self.camera_disconnect_button.setEnabled(False)
        camera_connection.addWidget(self.camera_disconnect_button, 1, 2, 1, 2)
        self.teach_zone_1_button = QPushButton("Teach Core")
        self.teach_zone_1_button.clicked.connect(lambda: self.start_teaching_zone(0))
        camera_connection.addWidget(self.teach_zone_1_button, 2, 0, 1, 2)
        self.clear_zones_button = QPushButton("Clear Core Learning")
        self.clear_zones_button.clicked.connect(lambda: self.clear_learning_type(0))
        camera_connection.addWidget(self.clear_zones_button, 2, 2, 1, 2)
        self.add_zone_1_sample_button = QPushButton("Add Core Sample")
        self.add_zone_1_sample_button.clicked.connect(lambda: self.start_teaching_zone(0, append=True))
        camera_connection.addWidget(self.add_zone_1_sample_button, 3, 0, 1, 2)
        self.reject_type_1_button = QPushButton("Mark False Core")
        self.reject_type_1_button.clicked.connect(lambda: self.start_rejecting_core(0))
        camera_connection.addWidget(self.reject_type_1_button, 3, 2, 1, 2)
        self.teach_pcb_button = QPushButton("Teach PCB")
        self.teach_pcb_button.clicked.connect(lambda: self.start_teaching_zone(1))
        camera_connection.addWidget(self.teach_pcb_button, 4, 0)
        self.add_pcb_sample_button = QPushButton("Add PCB Sample")
        self.add_pcb_sample_button.clicked.connect(lambda: self.start_teaching_zone(1, append=True))
        camera_connection.addWidget(self.add_pcb_sample_button, 4, 1)
        self.reject_pcb_button = QPushButton("Mark False PCB")
        self.reject_pcb_button.clicked.connect(lambda: self.start_rejecting_core(1))
        camera_connection.addWidget(self.reject_pcb_button, 4, 2, 1, 2)
        self.clear_pcb_button = QPushButton("Clear PCB Learning")
        self.clear_pcb_button.clicked.connect(lambda: self.clear_learning_type(1))
        camera_connection.addWidget(self.clear_pcb_button, 5, 0, 1, 4)
        self.panel_scan_button = QPushButton("Panel Scan (20 PCB / 40 Core)")
        self.panel_scan_button.clicked.connect(self.start_panel_scan)
        self.panel_scan_button.setEnabled(False)
        camera_connection.addWidget(self.panel_scan_button, 6, 0, 1, 4)
        camera_group_layout.addLayout(camera_connection)
        self.sample_library_label = QLabel("Samples: Core = 0, PCB = 0, false core = 0, false PCB = 0.")
        self.sample_library_label.setWordWrap(True)
        camera_group_layout.addWidget(self.sample_library_label)
        self.alignment_label = QLabel("Teach one PCB core example to detect all matching cores.")
        self.alignment_label.setWordWrap(True)
        camera_group_layout.addWidget(self.alignment_label)
        camera_layout.addWidget(camera_group)
        layout.addLayout(camera_layout, 2)

        controls = QVBoxLayout()
        controls.addWidget(self._build_connection_group())
        controls.addWidget(self._build_position_group())
        controls.addWidget(self._build_move_group())

        alignment_group = QGroupBox("Camera Alignment")
        alignment_layout = QVBoxLayout(alignment_group)
        self.calibrate_x_button = QPushButton("Calibrate X (+10 mm)")
        self.calibrate_x_button.clicked.connect(self.calibrate_x)
        self.calibrate_x_button.setEnabled(False)
        alignment_layout.addWidget(self.calibrate_x_button)
        self.align_x_button = QPushButton("Align X (max 2 mm)")
        self.align_x_button.clicked.connect(self.align_x)
        self.align_x_button.setEnabled(False)
        alignment_layout.addWidget(self.align_x_button)
        self.x_calibration_label = QLabel("X calibration: required")
        alignment_layout.addWidget(self.x_calibration_label)
        self.calibrate_y_button = QPushButton("Calibrate Y (+10 mm)")
        self.calibrate_y_button.clicked.connect(self.calibrate_y)
        self.calibrate_y_button.setEnabled(False)
        alignment_layout.addWidget(self.calibrate_y_button)
        self.y_calibration_label = QLabel("Y calibration: required")
        alignment_layout.addWidget(self.y_calibration_label)
        self.center_x_button = QPushButton("Center X on Camera")
        self.center_x_button.clicked.connect(self.center_x_on_camera)
        self.center_x_button.setEnabled(False)
        alignment_layout.addWidget(self.center_x_button)
        self.center_y_button = QPushButton("Center Y on Camera")
        self.center_y_button.clicked.connect(self.center_y_on_camera)
        self.center_y_button.setEnabled(False)
        alignment_layout.addWidget(self.center_y_button)
        self.next_core_button = QPushButton("Next Core")
        self.next_core_button.clicked.connect(self.go_to_next_core)
        self.next_core_button.setEnabled(False)
        alignment_layout.addWidget(self.next_core_button)
        controls.addWidget(alignment_group)

        self.status_label = QLabel("Select the controller port and connect.")
        self.status_label.setWordWrap(True)
        controls.addWidget(self.status_label)
        controls.addStretch()
        layout.addLayout(controls, 1)

    def _build_connection_group(self) -> QGroupBox:
        group = QGroupBox("Motion Connection")
        group_layout = QHBoxLayout(group)
        group_layout.addWidget(QLabel("Serial port"))
        self.port_combo = QComboBox()
        self._refresh_ports()
        group_layout.addWidget(self.port_combo, 1)
        self.refresh_button = QPushButton("Refresh")
        self.refresh_button.clicked.connect(self._refresh_ports)
        group_layout.addWidget(self.refresh_button)
        self.connect_button = QPushButton("Connect")
        self.connect_button.clicked.connect(self.connect_system)
        group_layout.addWidget(self.connect_button)
        self.disconnect_button = QPushButton("Disconnect")
        self.disconnect_button.clicked.connect(self.disconnect_system)
        self.disconnect_button.setEnabled(False)
        group_layout.addWidget(self.disconnect_button)
        return group

    def _build_position_group(self) -> QGroupBox:
        group = QGroupBox("Position")
        group_layout = QGridLayout(group)
        group_layout.addWidget(QLabel("X"), 0, 0)
        self.x_position_label = QLabel("0.000 mm")
        self.x_position_label.setFont(QFont("Courier", 11, QFont.Bold))
        group_layout.addWidget(self.x_position_label, 0, 1)
        group_layout.addWidget(QLabel("Y"), 1, 0)
        self.y_position_label = QLabel("0.000 mm")
        self.y_position_label.setFont(QFont("Courier", 11, QFont.Bold))
        group_layout.addWidget(self.y_position_label, 1, 1)
        return group

    def _build_move_group(self) -> QGroupBox:
        group = QGroupBox("Move To")
        group_layout = QGridLayout(group)
        self.x_spinbox = self._coordinate_input()
        self.y_spinbox = self._coordinate_input()
        self.speed_spinbox = QDoubleSpinBox()
        self.speed_spinbox.setRange(5.0, 1000.0)
        self.speed_spinbox.setValue(20.0)
        self.speed_spinbox.setDecimals(1)
        self.speed_spinbox.setSingleStep(5.0)
        self.speed_spinbox.setSuffix(" F")
        group_layout.addWidget(QLabel("X target"), 0, 0)
        group_layout.addWidget(self.x_spinbox, 0, 1)
        group_layout.addWidget(QLabel("Y target"), 1, 0)
        group_layout.addWidget(self.y_spinbox, 1, 1)
        group_layout.addWidget(QLabel("Feed"), 2, 0)
        group_layout.addWidget(self.speed_spinbox, 2, 1)
        self.move_button = QPushButton("Move")
        self.move_button.clicked.connect(self.move_to_position)
        self.move_button.setEnabled(False)
        group_layout.addWidget(self.move_button, 3, 0, 1, 2)
        return group

    @staticmethod
    def _coordinate_input() -> QDoubleSpinBox:
        control = QDoubleSpinBox()
        control.setRange(-300.0, 300.0)
        control.setDecimals(3)
        control.setSingleStep(1.0)
        control.setSuffix(" mm")
        return control

    def _refresh_ports(self) -> None:
        selected = self.port_combo.currentText() if hasattr(self, "port_combo") else "COM6"
        self.port_combo.clear()
        self.port_combo.addItems(discover_ports() or ["COM6"])
        index = self.port_combo.findText(selected)
        if index >= 0:
            self.port_combo.setCurrentIndex(index)

    def connect_system(self) -> None:
        try:
            port_name = self.port_combo.currentText()
            self.motion = MotionController(timeout_s=20.0)
            self.motion.connect(port_name)
            self.motion_thread = MotionThread(self.motion)
            self.motion_thread.motion_complete.connect(self.on_motion_complete)
            self.motion_thread.motion_error.connect(self.on_motion_error)
            self.current_x = self.current_y = 0.0
            self._set_position_labels()
            self.is_connected = True
            self._update_motion_ui()
            self.status_label.setText(f"Connected to {port_name}. Position origin set to 0.00, 0.00.")
        except Exception as exc:
            self.motion = None
            QMessageBox.critical(self, "Connection Error", str(exc))

    def disconnect_system(self) -> None:
        if self.motion_thread and self.motion_thread.isRunning():
            QMessageBox.warning(self, "Move in Progress", "Wait for the move to finish before disconnecting.")
            return
        if self.motion:
            self.motion.disconnect()
        self.motion = None
        self.motion_thread = None
        self.is_connected = False
        self._update_motion_ui()
        self.status_label.setText("Disconnected")

    def _update_motion_ui(self) -> None:
        moving = bool(self.motion_thread and self.motion_thread.isRunning())
        self.connect_button.setEnabled(not self.is_connected)
        self.disconnect_button.setEnabled(self.is_connected and not moving)
        self.move_button.setEnabled(self.is_connected and not moving)
        self.port_combo.setEnabled(not self.is_connected)
        self.refresh_button.setEnabled(not self.is_connected)
        can_align = self.is_connected and not moving and self.last_measurement is not None
        self.calibrate_x_button.setEnabled(can_align)
        self.align_x_button.setEnabled(can_align and self.pixels_per_mm_x is not None)
        self.calibrate_y_button.setEnabled(can_align)
        can_center = (
            can_align
            and self.x_axis_camera_response is not None
            and self.y_axis_camera_response is not None
            and self.camera_center_x is not None
            and self.camera_center_y is not None
        )
        self.center_x_button.setEnabled(can_center)
        self.center_y_button.setEnabled(can_center)
        self.next_core_button.setEnabled(can_center and self._core_navigation_ready and bool(self._reference_core_targets))

    def connect_camera(self) -> None:
        self.disconnect_camera()
        self._camera_session += 1
        self.camera_label.setText("Connecting to DroidCam...")
        self.camera_connect_button.setEnabled(False)
        self.camera_thread = CameraThread(
            self._camera_session,
            self.camera_ip_input.text().strip(),
            self.camera_port_input.value(),
            self.TEMPLATE_PATH,
        )
        self.camera_thread.frame_ready.connect(self.show_camera_frame)
        self.camera_thread.connection_changed.connect(self.on_camera_connection_changed)
        self.camera_thread.alignment_measurement_changed.connect(self.on_alignment_measurement)
        self.camera_thread.alignment_status_changed.connect(self.on_alignment_status)
        self.camera_thread.detection_counts_changed.connect(self.on_detection_counts)
        self.camera_thread.finished.connect(lambda thread=self.camera_thread: self.on_camera_thread_finished(thread))
        self.camera_thread.start()
        if self.camera_thread.loaded_saved_zones:
            self.alignment_label.setText("Saved PCB/core samples loaded. PCBs are blue; cores are green.")
        self.update_sample_library_label()

    def disconnect_camera(self) -> None:
        if self.camera_thread:
            self.camera_thread.stop()
            self._retired_camera_threads.append(self.camera_thread)
            self.camera_thread = None
        self._camera_session += 1
        self.camera_disconnect_button.setEnabled(False)
        self.camera_connect_button.setEnabled(True)
        self.panel_scan_button.setEnabled(False)
        self._panel_scan_active = False

    def on_camera_thread_finished(self, thread: CameraThread) -> None:
        if thread in self._retired_camera_threads:
            self._retired_camera_threads.remove(thread)
        thread.deleteLater()

    def show_camera_frame(self, session: int, image: QImage) -> None:
        if session != self._camera_session:
            return
        self.camera_label.show_image(image)

    def start_panel_scan(self) -> None:
        if not self.camera_thread or not self.camera_thread.isRunning():
            self.status_label.setText("Connect the camera before starting Panel Scan.")
            return
        core_samples, pcb_samples = self.camera_thread.aligner.sample_counts()
        if core_samples == 0 or pcb_samples == 0:
            self.status_label.setText("Teach at least one Core and one PCB sample before Panel Scan.")
            return
        self._panel_scan_active = True
        self._full_layout_capture_saved = False
        self.detected_pcb_count = 0
        self.detected_core_count = 0
        self._reference_primary_core = None
        self._reference_machine_position = None
        self._reference_core_targets = []
        self._core_navigation_ready = False
        self.panel_scan_button.setEnabled(False)
        self.panel_scan_button.setText("Scanning: 0/20 PCB, 0/40 Core")
        self.camera_thread.start_panel_scan()
        self.alignment_label.setText("Panel Scan active: searching the current view for 20 PCBs and 40 cores.")
        self.status_label.setText("Panel Scan started. Keep the panel and camera stationary.")

    def capture_startup_position(self) -> None:
        if not self.camera_thread or not self.camera_thread.isRunning():
            message = "The startup capture failed because the camera is not connected."
            self.status_label.setText(message)
            QMessageBox.warning(self, "Startup Capture", message)
            return
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"startup_{timestamp}_X{self.current_x:+.3f}_Y{self.current_y:+.3f}.jpg"
        path = self.STARTUP_CAPTURE_DIR / filename
        try:
            pcb_count, core_count, primary_x, primary_y, core_targets = self.camera_thread.save_latest_frame(path, self.current_x, self.current_y)
        except Exception as exc:
            message = f"The startup capture failed: {exc}"
            self.status_label.setText(message)
            QMessageBox.warning(self, "Startup Capture", message)
            return
        message = (
            f"Startup position photo saved at X={self.current_x:.3f} mm, Y={self.current_y:.3f} mm.\n"
            f"Detected: {pcb_count} PCBs and {core_count} cores.\n{path}"
        )
        self.status_label.setText(message)
        if pcb_count == self.EXPECTED_PCB_COUNT and core_count == self.EXPECTED_CORE_COUNT:
            self._full_layout_capture_saved = True
            if primary_x is not None and primary_y is not None:
                self._reference_primary_core = (primary_x, primary_y)
                self._reference_machine_position = (self.current_x, self.current_y)
                self._reference_core_targets = core_targets
                self._current_core_target_index = 0
                self._core_navigation_ready = False
            QMessageBox.information(self, "Startup Capture Complete", message + "\nCounts are correct.")
        else:
            QMessageBox.warning(
                self,
                "Startup Count Warning",
                message
                + f"\nExpected: {self.EXPECTED_PCB_COUNT} PCBs and {self.EXPECTED_CORE_COUNT} cores.",
            )

    def on_detection_counts(self, session: int, pcb_count: int, core_count: int) -> None:
        if session != self._camera_session:
            return
        self.detected_pcb_count = pcb_count
        self.detected_core_count = core_count
        if self._panel_scan_active:
            self.panel_scan_button.setText(f"Scanning: {pcb_count}/20 PCB, {core_count}/40 Core")
        if (
            self._panel_scan_active
            and
            not self._full_layout_capture_saved
            and pcb_count == self.EXPECTED_PCB_COUNT
            and core_count == self.EXPECTED_CORE_COUNT
        ):
            self._full_layout_capture_saved = True
            QTimer.singleShot(0, self.capture_full_layout)

    def capture_full_layout(self) -> None:
        if not self.camera_thread or not self.camera_thread.isRunning():
            self._full_layout_capture_saved = False
            return
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        path = self.STARTUP_CAPTURE_DIR / f"all_pcbs_cores_{timestamp}.jpg"
        try:
            pcb_count, core_count, primary_x, primary_y, core_targets = self.camera_thread.save_latest_frame(path, self.current_x, self.current_y)
        except Exception as exc:
            self._full_layout_capture_saved = False
            self.status_label.setText(f"Could not save the complete PCB/core photo: {exc}")
            return
        if pcb_count != self.EXPECTED_PCB_COUNT or core_count != self.EXPECTED_CORE_COUNT:
            self._full_layout_capture_saved = False
            return
        if primary_x is None or primary_y is None:
            self._full_layout_capture_saved = False
            return
        self._reference_primary_core = (primary_x, primary_y)
        self._reference_machine_position = (self.current_x, self.current_y)
        self._reference_core_targets = core_targets
        self._current_core_target_index = 0
        self._core_navigation_ready = False
        self._panel_scan_active = False
        self.camera_thread.stop_image_processing(freeze_display=False)
        self.panel_scan_button.setText("Panel Scan (20 PCB / 40 Core)")
        self.panel_scan_button.setEnabled(True)
        message = f"All {pcb_count} PCBs and {core_count} cores were detected and saved.\n{path}"
        self.status_label.setText(message)
        self.alignment_label.setText(
            "Panel locked: 20 PCBs and 40 cores saved. Image processing is stopped; live camera remains active."
        )
        self._update_motion_ui()
        QMessageBox.information(
            self,
            "Panel Scan Complete",
            message + "\nImage processing has stopped; the live camera remains active.",
        )

    def on_camera_connection_changed(self, session: int, connected: bool, message: str) -> None:
        if session != self._camera_session:
            return
        self.camera_connect_button.setEnabled(not connected)
        self.camera_disconnect_button.setEnabled(connected)
        self.camera_ip_input.setEnabled(not connected)
        self.camera_port_input.setEnabled(not connected)
        self.panel_scan_button.setEnabled(connected and not self._panel_scan_active)
        if not connected:
            self.camera_label.setText(message)
        self.status_label.setText(message)

    def start_teaching_zone(self, index: int, append: bool = False) -> None:
        if not self.camera_thread or not self.camera_thread.isRunning():
            self.status_label.setText("Connect the camera before teaching a PCB core.")
            return
        self._teach_zone_request = (index, append)
        self._reject_core_request = None
        self.camera_label.set_selection_enabled(True)
        action = "Add a new example for" if append else "Teach"
        target = "PCB core" if index == 0 else "complete PCB board"
        self.status_label.setText(f"{action} {target}; draw a tight rectangle around it.")

    def start_rejecting_core(self, index: int) -> None:
        if not self.camera_thread or not self.camera_thread.isRunning():
            self.status_label.setText("Connect the camera before marking a false detection.")
            return
        if self.camera_thread.aligner.sample_counts()[index] == 0:
            target = "core" if index == 0 else "PCB"
            self.status_label.setText(f"Teach the {target} before adding false examples.")
            return
        self._teach_zone_request = None
        self._reject_core_request = index
        self.camera_label.set_selection_enabled(True)
        target = "core" if index == 0 else "PCB"
        self.status_label.setText(f"Draw a tight rectangle around one false {target} detection.")

    def on_zone_selected(self, x: int, y: int, width: int, height: int) -> None:
        if not self.camera_thread:
            return
        if self._reject_core_request is not None:
            index = self._reject_core_request
            try:
                answer = QMessageBox.question(
                    self,
                    "Confirm False Detection",
                    "Mark this frame as NOT a core?" if index == 0 else "Mark this frame as NOT a PCB?",
                    QMessageBox.Yes | QMessageBox.No,
                    QMessageBox.No,
                )
                if answer == QMessageBox.Yes:
                    self.camera_thread.teach_negative(index, Rectangle(x, y, width, height))
                    target = "core" if index == 0 else "PCB"
                    self.status_label.setText(f"False {target} example saved and will be rejected.")
                    self.update_sample_library_label()
                else:
                    self.status_label.setText("False-detection example was not saved.")
            except Exception as exc:
                self.status_label.setText(f"Could not save false detection: {exc}")
            finally:
                self._reject_core_request = None
                self.camera_label.clear_selection()
            return
        if self._teach_zone_request is None:
            return
        index, append = self._teach_zone_request
        try:
            answer = QMessageBox.question(
                self,
                "Confirm Frame",
                "Accept this PCB core sample?" if index == 0 else "Accept this complete PCB sample?",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            if answer != QMessageBox.Yes:
                target = "Core" if index == 0 else "PCB"
                self.status_label.setText(f"{target} sample was not saved. Select it again when ready.")
                return
            self.camera_thread.teach_zone(index, Rectangle(x, y, width, height), append)
            count_1, count_2 = self.camera_thread.aligner.sample_counts()
            target = "Core" if index == 0 else "PCB"
            self.status_label.setText(f"{target} saved. Samples: Core = {count_1}, PCB = {count_2}.")
            self.update_sample_library_label()
        except Exception as exc:
            self.status_label.setText(f"Could not teach PCB core: {exc}")
        finally:
            self._teach_zone_request = None
            self.camera_label.clear_selection()

    def clear_learning_type(self, index: int) -> None:
        if self.camera_thread:
            self.camera_thread.clear_learning_type(index)
            self.camera_thread.stop_image_processing(freeze_display=False)
        self._panel_scan_active = False
        self._full_layout_capture_saved = False
        self.panel_scan_button.setText("Panel Scan (20 PCB / 40 Core)")
        self.panel_scan_button.setEnabled(bool(self.camera_thread and self.camera_thread.isRunning()))
        self.last_measurement = None
        self.pixels_per_mm_x = None
        self.center_pixels_per_mm_x = None
        self.x_axis_camera_response = None
        self.y_axis_camera_response = None
        self.camera_center_x = None
        self.camera_center_y = None
        self._reference_primary_core = None
        self._reference_machine_position = None
        self._reference_core_targets = []
        self._core_navigation_ready = False
        self._navigation_target_label = None
        self.x_calibration_label.setText("X calibration: required")
        self.y_calibration_label.setText("Y calibration: required")
        target = "Core" if index == 0 else "PCB"
        self.alignment_label.setText(f"{target} learning cleared.")
        self.update_sample_library_label()
        self._update_motion_ui()

    def update_sample_library_label(self) -> None:
        if not self.camera_thread:
            self.sample_library_label.setText("Core sample library: camera is disconnected.")
            return
        count_1, count_2 = self.camera_thread.aligner.sample_counts()
        negative_1, negative_2 = self.camera_thread.aligner.negative_counts()
        self.sample_library_label.setText(
            f"Samples: Core = {count_1}, PCB = {count_2}, false core = {negative_1}, false PCB = {negative_2}."
        )

    def on_alignment_status(self, session: int, message: str) -> None:
        if session != self._camera_session:
            return
        self.alignment_label.setText(message)

    def _set_target_search_enabled(self, enabled: bool) -> None:
        if self.camera_thread:
            self.camera_thread.set_target_search_enabled(enabled)

    def on_alignment_measurement(self, session: int, midpoint_x: float, midpoint_y: float, error_x: float, error_y: float, score_1: float, score_2: float, center_x: float, center_y: float, primary_x: float, primary_y: float) -> None:
        if session != self._camera_session:
            return
        self._measurement_serial += 1
        self.last_measurement = AlignmentMeasurement(midpoint_x, midpoint_y, error_x, error_y, score_1, score_2, primary_x, primary_y)
        self.camera_center_x = center_x
        self.camera_center_y = center_y
        self.alignment_label.setText(
            f"Detected. X error: {error_x:+.1f} px, Y error: {error_y:+.1f} px. "
            f"Scores: {score_1:.2f}, {score_2:.2f}."
        )
        self._update_motion_ui()

    def move_to_position(self) -> None:
        self._set_target_search_enabled(False)
        self._start_move(self.x_spinbox.value(), self.y_spinbox.value(), "Moving")

    def _start_move(self, target_x: float, target_y: float, action: str) -> None:
        if not self.motion_thread or self.motion_thread.isRunning():
            return
        speed = self.speed_spinbox.value()
        distance = abs(target_x - self.current_x) + abs(target_y - self.current_y)
        timeout_s = max(20.0, (distance * 100.0 / speed) + 15.0)
        self.motion_thread.set_target(target_x, target_y, speed, timeout_s)
        self.status_label.setText(f"{action}: X={target_x:.3f} mm, Y={target_y:.3f} mm at F={speed:.1f}...")
        self.motion_thread.start()
        self._update_motion_ui()

    def on_motion_complete(self, x: float, y: float) -> None:
        self.current_x, self.current_y = x, y
        self._set_position_labels()
        self._update_motion_ui()
        if self._pending_calibration:
            self._calibration_wait_serial = self._measurement_serial
            self.status_label.setText("X calibration move complete. Waiting 5 seconds for an updated camera frame...")
            QTimer.singleShot(self.CAMERA_SETTLE_DELAY_MS, self.finish_x_calibration)
        elif self._pending_y_calibration:
            self._calibration_wait_serial = self._measurement_serial
            self.status_label.setText("Y calibration move complete. Waiting 5 seconds for an updated camera frame...")
            QTimer.singleShot(self.CAMERA_SETTLE_DELAY_MS, self.finish_y_calibration)
        elif self._auto_center_phase == "x":
            self._auto_center_phase = "waiting_y"
            self.status_label.setText("PCB 1 Core 1 X centering complete. Waiting 5 seconds before Y centering...")
            QTimer.singleShot(self.CAMERA_SETTLE_DELAY_MS, self._continue_auto_center_y)
        elif self._auto_center_phase == "y":
            self._auto_center_phase = None
            self._auto_center_y_correction = None
            self._current_core_target_index = 0
            self._core_navigation_ready = True
            self._set_target_search_enabled(True)
            message = "PCB 1 Core 1 automatic X/Y centering is complete."
            self.status_label.setText(message)
            self._update_motion_ui()
            QMessageBox.information(self, "Automatic Centering Complete", message)
        elif self._navigation_target_label is not None:
            message = f"Reached {self._navigation_target_label}."
            self._navigation_target_label = None
            self.status_label.setText(message)
            self._update_motion_ui()
        else:
            self.status_label.setText("Move complete")

    def on_motion_error(self, error: str) -> None:
        self._pending_calibration = None
        self._pending_y_calibration = None
        self._calibration_wait_serial = None
        self._pending_calibration_frame = None
        self._auto_center_phase = None
        self._auto_center_y_correction = None
        self._navigation_target_label = None
        self.status_label.setText(f"Move failed: {error}")
        self._update_motion_ui()

    def calibrate_x(self) -> None:
        if not self.last_measurement or not self.camera_thread:
            return
        self._set_target_search_enabled(False)
        try:
            self._pending_calibration_frame = self.camera_thread.latest_frame_copy()
        except RuntimeError as exc:
            self.status_label.setText(f"X calibration failed: {exc}")
            return
        self.x_axis_camera_response = None
        self._pending_calibration = (
            self.last_measurement.midpoint_x,
            self.last_measurement.midpoint_y,
            self.CALIBRATION_DISTANCE_MM,
        )
        self._start_move(self.current_x + self.CALIBRATION_DISTANCE_MM, self.current_y, "Calibrating X")

    def finish_x_calibration(self) -> None:
        if not self._pending_calibration:
            return
        _, _, distance_mm = self._pending_calibration
        self._pending_calibration = None
        self._calibration_wait_serial = None
        shifts = self._calibration_frame_shift()
        if shifts is None:
            return
        horizontal_pixel_shift, vertical_pixel_shift, response = shifts
        if abs(horizontal_pixel_shift) < 5.0 and abs(vertical_pixel_shift) < 5.0:
            self.status_label.setText("Calibration failed: camera saw too little movement from the X axis.")
            return
        self.pixels_per_mm_x = horizontal_pixel_shift / distance_mm if abs(horizontal_pixel_shift) >= 5.0 else None
        self.center_pixels_per_mm_x = vertical_pixel_shift / distance_mm if abs(vertical_pixel_shift) >= 5.0 else None
        self.x_axis_camera_response = (horizontal_pixel_shift / distance_mm, vertical_pixel_shift / distance_mm)
        horizontal_status = (
            f"{self.pixels_per_mm_x:.2f} horizontal px/mm"
            if self.pixels_per_mm_x is not None
            else "horizontal response unavailable"
        )
        center_status = (
            f", center {self.center_pixels_per_mm_x:.2f} vertical px/mm"
            if self.center_pixels_per_mm_x is not None
            else ", center-line response unavailable"
        )
        self.x_calibration_label.setText(f"X calibration: {horizontal_status}{center_status}")
        self.status_label.setText(f"X calibration complete from whole-frame motion (confidence {response:.2f}). Calibrate Y next.")
        self._update_motion_ui()
        QMessageBox.information(self, "X Calibration Complete", "X axis calibration completed using the updated camera image.")

    def align_x(self) -> None:
        if not self.last_measurement or not self.pixels_per_mm_x:
            return
        correction_mm = self.last_measurement.error_x / self.pixels_per_mm_x
        if abs(correction_mm) < 0.05:
            self.status_label.setText("X is already aligned within 0.05 mm.")
            return
        correction_mm = max(-self.MAX_AUTO_X_STEP_MM, min(self.MAX_AUTO_X_STEP_MM, correction_mm))
        self._start_move(self.current_x + correction_mm, self.current_y, "Aligning X")

    def calibrate_y(self) -> None:
        if not self.last_measurement or not self.camera_thread:
            return
        self._set_target_search_enabled(False)
        try:
            self._pending_calibration_frame = self.camera_thread.latest_frame_copy()
        except RuntimeError as exc:
            self.status_label.setText(f"Y calibration failed: {exc}")
            return
        self.y_axis_camera_response = None
        self._pending_y_calibration = (
            self.last_measurement.midpoint_x,
            self.last_measurement.midpoint_y,
            self.CALIBRATION_DISTANCE_MM,
        )
        self._start_move(self.current_x, self.current_y + self.CALIBRATION_DISTANCE_MM, "Calibrating Y")

    def finish_y_calibration(self) -> None:
        if not self._pending_y_calibration:
            return
        _, _, distance_mm = self._pending_y_calibration
        self._pending_y_calibration = None
        self._calibration_wait_serial = None
        shifts = self._calibration_frame_shift()
        if shifts is None:
            return
        horizontal_shift, vertical_shift, response = shifts
        if abs(horizontal_shift) < 5.0 and abs(vertical_shift) < 5.0:
            self.status_label.setText("Y calibration failed: camera saw too little movement from the Y axis.")
            return
        self.y_axis_camera_response = (horizontal_shift / distance_mm, vertical_shift / distance_mm)
        self.y_calibration_label.setText(
            f"Y calibration: X {self.y_axis_camera_response[0]:.2f}, Y {self.y_axis_camera_response[1]:.2f} px/mm"
        )
        self.status_label.setText(f"Y calibration complete from whole-frame motion (confidence {response:.2f}).")
        self._update_motion_ui()
        QMessageBox.information(self, "Y Calibration Complete", "Y axis calibration completed using the updated camera image.")
        QTimer.singleShot(0, self.start_auto_center_primary_core)

    def _calibration_frame_shift(self) -> Optional[tuple[float, float, float]]:
        if self._pending_calibration_frame is None or not self.camera_thread:
            self.status_label.setText("Calibration failed: the before-move camera frame is unavailable.")
            return None
        try:
            after_frame = self.camera_thread.latest_frame_copy()
        except RuntimeError as exc:
            self.status_label.setText(f"Calibration failed: {exc}")
            return None
        before_frame = self._pending_calibration_frame
        self._pending_calibration_frame = None
        before_gray = cv2.equalizeHist(cv2.cvtColor(before_frame, cv2.COLOR_BGR2GRAY))
        after_gray = cv2.equalizeHist(cv2.cvtColor(after_frame, cv2.COLOR_BGR2GRAY))
        if before_gray.shape != after_gray.shape:
            after_gray = cv2.resize(after_gray, (before_gray.shape[1], before_gray.shape[0]))
        window = cv2.createHanningWindow((before_gray.shape[1], before_gray.shape[0]), cv2.CV_32F)
        phase_shift, _ = cv2.phaseCorrelate(before_gray.astype("float32"), after_gray.astype("float32"), window)
        points_before = cv2.goodFeaturesToTrack(
            before_gray,
            maxCorners=1200,
            qualityLevel=0.01,
            minDistance=7,
            blockSize=7,
        )
        if points_before is None or len(points_before) < 30:
            self.status_label.setText("Calibration failed: too few trackable image features.")
            return None
        initial_points = points_before + np.array(phase_shift, dtype=np.float32).reshape(1, 1, 2)
        points_after, forward_status, _ = cv2.calcOpticalFlowPyrLK(
            before_gray,
            after_gray,
            points_before,
            initial_points,
            winSize=(31, 31),
            maxLevel=4,
            criteria=(cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_COUNT, 40, 0.01),
            flags=cv2.OPTFLOW_USE_INITIAL_FLOW,
        )
        if points_after is None or forward_status is None:
            self.status_label.setText("Calibration failed: optical-flow tracking did not converge.")
            return None
        points_back, backward_status, _ = cv2.calcOpticalFlowPyrLK(
            after_gray,
            before_gray,
            points_after,
            None,
            winSize=(31, 31),
            maxLevel=4,
            criteria=(cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_COUNT, 40, 0.01),
        )
        if points_back is None or backward_status is None:
            self.status_label.setText("Calibration failed: reverse optical-flow validation failed.")
            return None
        round_trip_error = np.linalg.norm(points_before.reshape(-1, 2) - points_back.reshape(-1, 2), axis=1)
        valid = (forward_status.ravel() == 1) & (backward_status.ravel() == 1) & (round_trip_error < 1.5)
        source = points_before.reshape(-1, 2)[valid]
        destination = points_after.reshape(-1, 2)[valid]
        if len(source) < 25:
            self.status_label.setText("Calibration failed: too few common features remained inside the image.")
            return None
        transform, inlier_mask = cv2.estimateAffinePartial2D(
            source,
            destination,
            method=cv2.RANSAC,
            ransacReprojThreshold=2.5,
            maxIters=4000,
            confidence=0.995,
            refineIters=20,
        )
        if transform is None or inlier_mask is None:
            self.status_label.setText("Calibration failed: RANSAC could not find consistent image motion.")
            return None
        inlier_count = int(inlier_mask.sum())
        inlier_ratio = inlier_count / len(source)
        scale = float(np.hypot(transform[0, 0], transform[0, 1]))
        rotation_degrees = float(np.degrees(np.arctan2(transform[1, 0], transform[0, 0])))
        if inlier_count < 20 or inlier_ratio < 0.45:
            self.status_label.setText(f"Calibration failed: only {inlier_count}/{len(source)} feature tracks agreed.")
            return None
        if not 0.98 <= scale <= 1.02 or abs(rotation_degrees) > 2.0:
            self.status_label.setText("Calibration failed: detected motion was not a clean X/Y translation.")
            return None
        return float(transform[0, 2]), float(transform[1, 2]), float(inlier_ratio)

    def start_auto_center_primary_core(self) -> None:
        self._set_target_search_enabled(False)
        if self._reference_primary_core is None or self._reference_machine_position is None:
            self.status_label.setText("Could not center PCB 1 Core 1: the complete 20-PCB/40-core reference photo is not available.")
            return
        corrections = self._camera_center_corrections(self._reference_primary_core)
        if corrections is None:
            self.status_label.setText("Could not center PCB 1 Core 1 from the saved reference photo.")
            return
        correction_x, correction_y = corrections
        target_x = self._reference_machine_position[0] + correction_x
        target_y = self._reference_machine_position[1] + correction_y
        self._auto_center_y_correction = target_y
        if abs(target_x - self.current_x) < 0.05:
            self._auto_center_phase = "waiting_y"
            QTimer.singleShot(0, self._continue_auto_center_y)
            return
        self._auto_center_phase = "x"
        self._start_move(target_x, self.current_y, "Centering PCB 1 Core 1 on X from saved photo")

    def _continue_auto_center_y(self) -> None:
        if self._auto_center_y_correction is None:
            self._auto_center_phase = None
            self.status_label.setText("Could not center PCB 1 Core 1 on Y: saved-photo correction is unavailable.")
            return
        target_y = self._auto_center_y_correction
        if abs(target_y - self.current_y) < 0.05:
            self._auto_center_phase = None
            self._auto_center_y_correction = None
            self._current_core_target_index = 0
            self._core_navigation_ready = True
            self._set_target_search_enabled(True)
            message = "PCB 1 Core 1 is already centered on Y; automatic centering is complete."
            self.status_label.setText(message)
            self._update_motion_ui()
            QMessageBox.information(self, "Automatic Centering Complete", message)
            return
        self._auto_center_phase = "y"
        self._start_move(self.current_x, target_y, "Centering PCB 1 Core 1 on Y from saved photo")

    def _camera_center_corrections(self, target: Optional[tuple[float, float]] = None) -> Optional[tuple[float, float]]:
        if (
            not self.last_measurement
            or self.x_axis_camera_response is None
            or self.y_axis_camera_response is None
            or self.camera_center_x is None
            or self.camera_center_y is None
        ):
            return
        target_x = target[0] if target is not None else (self.last_measurement.primary_x if self.last_measurement.primary_x is not None else self.last_measurement.midpoint_x)
        target_y = target[1] if target is not None else (self.last_measurement.primary_y if self.last_measurement.primary_y is not None else self.last_measurement.midpoint_y)
        error_x = self.camera_center_x - target_x
        error_y = self.camera_center_y - target_y
        x_dx, x_dy = self.x_axis_camera_response
        y_dx, y_dy = self.y_axis_camera_response
        determinant = x_dx * y_dy - y_dx * x_dy
        if abs(determinant) < 0.01:
            self.status_label.setText("Centering failed: X/Y camera calibration directions are too similar.")
            return None
        correction_x = (error_x * y_dy - y_dx * error_y) / determinant
        correction_y = (x_dx * error_y - error_x * x_dy) / determinant
        return correction_x, correction_y

    def center_x_on_camera(self) -> None:
        corrections = self._camera_center_corrections()
        if corrections is None:
            return
        correction_x, _ = corrections
        if abs(correction_x) < 0.05:
            self.status_label.setText("X is already centered within 0.05 mm.")
            return
        self._start_move(self.current_x + correction_x, self.current_y, "Centering X on camera")

    def center_y_on_camera(self) -> None:
        corrections = self._camera_center_corrections()
        if corrections is None:
            return
        _, correction_y = corrections
        if abs(correction_y) < 0.05:
            self.status_label.setText("Y is already centered within 0.05 mm.")
            return
        self._start_move(self.current_x, self.current_y + correction_y, "Centering Y on camera")

    def go_to_next_core(self) -> None:
        if (
            not self._core_navigation_ready
            or not self._reference_core_targets
            or self._reference_machine_position is None
        ):
            return
        next_index = (self._current_core_target_index + 1) % len(self._reference_core_targets)
        pcb_number, core_number, pixel_x, pixel_y = self._reference_core_targets[next_index]
        corrections = self._camera_center_corrections((pixel_x, pixel_y))
        if corrections is None:
            self.status_label.setText(f"Could not calculate the target for PCB {pcb_number} Core {core_number}.")
            return
        correction_x, correction_y = corrections
        target_x = self._reference_machine_position[0] + correction_x
        target_y = self._reference_machine_position[1] + correction_y
        self._current_core_target_index = next_index
        self._navigation_target_label = f"PCB {pcb_number} Core {core_number}"
        self._set_target_search_enabled(True)
        self._start_move(target_x, target_y, f"Moving to {self._navigation_target_label}")

    def _set_position_labels(self) -> None:
        self.x_position_label.setText(f"{self.current_x:.3f} mm")
        self.y_position_label.setText(f"{self.current_y:.3f} mm")

    def closeEvent(self, event) -> None:  # type: ignore[no-untyped-def]
        if self.motion_thread and self.motion_thread.isRunning():
            event.ignore()
            QMessageBox.warning(self, "Move in Progress", "Wait for the move to finish before closing.")
            return
        self.disconnect_system()
        self.disconnect_camera()
        event.accept()


def main() -> None:
    app = QtWidgets.QApplication(sys.argv)
    window = PCBPrinterGUI()
    window.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
