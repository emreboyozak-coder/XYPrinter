"""Desktop control for motion and two-zone PCB camera alignment."""

from __future__ import annotations

import logging
import sys
import threading
from pathlib import Path
from typing import Optional

import cv2
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
            self._drag_start = None
            self._drag_end = None
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
    """Reads DroidCam and applies two-zone template alignment off the GUI thread."""

    frame_ready = pyqtSignal(int, QImage)
    connection_changed = pyqtSignal(int, bool, str)
    alignment_measurement_changed = pyqtSignal(int, float, float, float, float, float, float)
    alignment_status_changed = pyqtSignal(int, str)

    def __init__(self, session: int, ip: str, port: int, template_path: Path) -> None:
        super().__init__()
        self.session = session
        self.url = f"http://{ip}:{port}/video"
        self.template_path = template_path
        self._running = True
        self._frame_lock = threading.Lock()
        self._latest_frame: Optional[object] = None
        self.aligner = PrintZoneAligner()
        self.loaded_saved_zones = self.aligner.load(template_path)
        self._last_status = ""

    def stop(self) -> None:
        self._running = False

    def teach_zone(self, index: int, rectangle: Rectangle, append: bool) -> None:
        with self._frame_lock:
            if self._latest_frame is None:
                raise RuntimeError("No camera frame is available")
            frame = self._latest_frame.copy()
        self.aligner.teach(index, frame, rectangle, append=append)
        self.aligner.save(self.template_path)

    def clear_zones(self) -> None:
        self.aligner.clear()
        self.template_path.unlink(missing_ok=True)

    def _emit_status(self, status: str) -> None:
        if status != self._last_status:
            self._last_status = status
            self.alignment_status_changed.emit(self.session, status)

    def run(self) -> None:
        camera = cv2.VideoCapture()
        camera.set(cv2.CAP_PROP_OPEN_TIMEOUT_MSEC, 3000)
        camera.set(cv2.CAP_PROP_READ_TIMEOUT_MSEC, 3000)
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

        self.connection_changed.emit(self.session, True, f"Camera connected: {self.url}")
        while self._running:
            with self._frame_lock:
                self._latest_frame = frame.copy()

            display_frame, measurement, status = self.aligner.process(frame)
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
                )

            rgb = cv2.cvtColor(display_frame, cv2.COLOR_BGR2RGB)
            height, width, channels = rgb.shape
            self.frame_ready.emit(self.session, QImage(rgb.data, width, height, channels * width, QImage.Format_RGB888).copy())
            ok, frame = camera.read()
            if not ok or frame is None:
                self._emit_status("Camera stream interrupted")
                break

        camera.release()


class PCBPrinterGUI(QMainWindow):
    """Control surface for verified motion plus supervised camera alignment."""

    CALIBRATION_DISTANCE_MM = 10.0
    MAX_AUTO_X_STEP_MM = 2.0
    TEMPLATE_PATH = Path(__file__).resolve().parents[4] / "config" / "print-zone-templates.npz"

    def __init__(self) -> None:
        super().__init__()
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
        self._teach_zone_request: Optional[tuple[int, bool]] = None
        self._pending_calibration: Optional[tuple[float, float]] = None

        self._build_ui()
        logging.basicConfig(level=logging.INFO)
        QTimer.singleShot(0, self.connect_camera)

    def _build_ui(self) -> None:
        central = QWidget()
        self.setCentralWidget(central)
        layout = QHBoxLayout(central)

        camera_layout = QVBoxLayout()
        camera_group = QGroupBox("DroidCam and Print-Zone Alignment")
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
        self.teach_zone_1_button = QPushButton("Teach Zone 1")
        self.teach_zone_1_button.clicked.connect(lambda: self.start_teaching_zone(0))
        camera_connection.addWidget(self.teach_zone_1_button, 2, 0)
        self.teach_zone_2_button = QPushButton("Teach Zone 2")
        self.teach_zone_2_button.clicked.connect(lambda: self.start_teaching_zone(1))
        camera_connection.addWidget(self.teach_zone_2_button, 2, 1)
        self.clear_zones_button = QPushButton("Clear Zones")
        self.clear_zones_button.clicked.connect(self.clear_zones)
        camera_connection.addWidget(self.clear_zones_button, 2, 2, 1, 2)
        self.add_zone_1_sample_button = QPushButton("Add Zone 1 Sample")
        self.add_zone_1_sample_button.clicked.connect(lambda: self.start_teaching_zone(0, append=True))
        camera_connection.addWidget(self.add_zone_1_sample_button, 3, 0, 1, 2)
        self.add_zone_2_sample_button = QPushButton("Add Zone 2 Sample")
        self.add_zone_2_sample_button.clicked.connect(lambda: self.start_teaching_zone(1, append=True))
        camera_connection.addWidget(self.add_zone_2_sample_button, 3, 2, 1, 2)
        camera_group_layout.addLayout(camera_connection)
        self.sample_library_label = QLabel("Sample library: Zone 1 = 0, Zone 2 = 0. Add as many samples as needed.")
        self.sample_library_label.setWordWrap(True)
        camera_group_layout.addWidget(self.sample_library_label)
        self.alignment_label = QLabel("Teach both 11 x 5 mm print targets; matching context is captured automatically.")
        self.alignment_label.setWordWrap(True)
        camera_group_layout.addWidget(self.alignment_label)
        camera_layout.addWidget(camera_group)
        layout.addLayout(camera_layout, 2)

        controls = QVBoxLayout()
        controls.addWidget(self._build_connection_group())
        controls.addWidget(self._build_position_group())
        controls.addWidget(self._build_move_group())

        alignment_group = QGroupBox("X Alignment")
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
        self.camera_thread.finished.connect(lambda thread=self.camera_thread: self.on_camera_thread_finished(thread))
        self.camera_thread.start()
        if self.camera_thread.loaded_saved_zones:
            self.alignment_label.setText("Saved print zones loaded. Confirm the red and green rectangles match the board.")
        self.update_sample_library_label()

    def disconnect_camera(self) -> None:
        if self.camera_thread:
            self.camera_thread.stop()
            self._retired_camera_threads.append(self.camera_thread)
            self.camera_thread = None
        self._camera_session += 1
        self.camera_disconnect_button.setEnabled(False)
        self.camera_connect_button.setEnabled(True)

    def on_camera_thread_finished(self, thread: CameraThread) -> None:
        if thread in self._retired_camera_threads:
            self._retired_camera_threads.remove(thread)
        thread.deleteLater()

    def show_camera_frame(self, session: int, image: QImage) -> None:
        if session != self._camera_session:
            return
        self.camera_label.show_image(image)

    def on_camera_connection_changed(self, session: int, connected: bool, message: str) -> None:
        if session != self._camera_session:
            return
        self.camera_connect_button.setEnabled(not connected)
        self.camera_disconnect_button.setEnabled(connected)
        self.camera_ip_input.setEnabled(not connected)
        self.camera_port_input.setEnabled(not connected)
        if not connected:
            self.camera_label.setText(message)
        self.status_label.setText(message)

    def start_teaching_zone(self, index: int, append: bool = False) -> None:
        if not self.camera_thread or not self.camera_thread.isRunning():
            self.status_label.setText("Connect the camera before teaching a print zone.")
            return
        self._teach_zone_request = (index, append)
        self.camera_label.set_selection_enabled(True)
        action = "Add a new example for" if append else "Set the red target for"
        self.status_label.setText(f"{action} 11 x 5 mm print zone {index + 1}; context is added automatically.")

    def on_zone_selected(self, x: int, y: int, width: int, height: int) -> None:
        if self._teach_zone_request is None or not self.camera_thread:
            return
        index, append = self._teach_zone_request
        try:
            self.camera_thread.teach_zone(index, Rectangle(x, y, width, height), append)
            count_1, count_2 = self.camera_thread.aligner.sample_counts()
            self.status_label.setText(f"Zone {index + 1} saved. Samples: Zone 1 = {count_1}, Zone 2 = {count_2}.")
            self.update_sample_library_label()
        except Exception as exc:
            self.status_label.setText(f"Could not teach zone: {exc}")
        finally:
            self._teach_zone_request = None

    def clear_zones(self) -> None:
        if self.camera_thread:
            self.camera_thread.clear_zones()
        self.last_measurement = None
        self.pixels_per_mm_x = None
        self.x_calibration_label.setText("X calibration: required")
        self.alignment_label.setText("Teach both 11 x 5 mm print targets; matching context is captured automatically.")
        self.update_sample_library_label()
        self._update_motion_ui()

    def update_sample_library_label(self) -> None:
        if not self.camera_thread:
            self.sample_library_label.setText("Sample library: camera is disconnected.")
            return
        count_1, count_2 = self.camera_thread.aligner.sample_counts()
        self.sample_library_label.setText(
            f"Sample library: Zone 1 = {count_1}, Zone 2 = {count_2}. Add as many samples as needed."
        )

    def on_alignment_status(self, session: int, message: str) -> None:
        if session != self._camera_session:
            return
        self.alignment_label.setText(message)

    def on_alignment_measurement(self, session: int, midpoint_x: float, midpoint_y: float, error_x: float, error_y: float, score_1: float, score_2: float) -> None:
        if session != self._camera_session:
            return
        self.last_measurement = AlignmentMeasurement(midpoint_x, midpoint_y, error_x, error_y, score_1, score_2)
        self.alignment_label.setText(
            f"Detected. X error: {error_x:+.1f} px, Y error: {error_y:+.1f} px. "
            f"Scores: {score_1:.2f}, {score_2:.2f}."
        )
        self._update_motion_ui()

    def move_to_position(self) -> None:
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
            self.status_label.setText("Calibration move complete. Reading camera alignment...")
            QTimer.singleShot(1000, self.finish_x_calibration)
        else:
            self.status_label.setText("Move complete")

    def on_motion_error(self, error: str) -> None:
        self._pending_calibration = None
        self.status_label.setText(f"Move failed: {error}")
        self._update_motion_ui()

    def calibrate_x(self) -> None:
        if not self.last_measurement:
            return
        self._pending_calibration = (self.last_measurement.midpoint_x, self.CALIBRATION_DISTANCE_MM)
        self._start_move(self.current_x + self.CALIBRATION_DISTANCE_MM, self.current_y, "Calibrating X")

    def finish_x_calibration(self) -> None:
        if not self._pending_calibration:
            return
        start_x, distance_mm = self._pending_calibration
        self._pending_calibration = None
        if not self.last_measurement:
            self.status_label.setText("Calibration failed: no current print-zone detection.")
            return
        pixel_shift = self.last_measurement.midpoint_x - start_x
        if abs(pixel_shift) < 5.0:
            self.status_label.setText("Calibration failed: camera saw too little X movement.")
            return
        self.pixels_per_mm_x = pixel_shift / distance_mm
        self.x_calibration_label.setText(f"X calibration: {self.pixels_per_mm_x:.2f} px/mm")
        self.status_label.setText("X calibration complete. Use Align X for bounded corrections.")
        self._update_motion_ui()

    def align_x(self) -> None:
        if not self.last_measurement or not self.pixels_per_mm_x:
            return
        correction_mm = self.last_measurement.error_x / self.pixels_per_mm_x
        if abs(correction_mm) < 0.05:
            self.status_label.setText("X is already aligned within 0.05 mm.")
            return
        correction_mm = max(-self.MAX_AUTO_X_STEP_MM, min(self.MAX_AUTO_X_STEP_MM, correction_mm))
        self._start_move(self.current_x + correction_mm, self.current_y, "Aligning X")

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
