"""Desktop control for the verified two-axis serial motion workflow."""

from __future__ import annotations

import logging
import sys
from typing import Optional

import cv2
from PyQt5 import QtWidgets
from PyQt5.QtCore import Qt, QThread, QTimer, pyqtSignal
from PyQt5.QtGui import QFont, QImage, QPixmap
from PyQt5.QtWidgets import (
    QComboBox,
    QCheckBox,
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
from marker.vision.fiducials import detect_fiducial_pair, draw_fiducial_overlay

logger = logging.getLogger(__name__)


class MotionThread(QThread):
    """Runs a single blocking firmware move without freezing the window."""

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
        self.target_x, self.target_y, self.speed = x, y, speed
        self.timeout_s = timeout_s

    def run(self) -> None:
        try:
            self.controller.move_to(self.target_x, self.target_y, self.speed, self.timeout_s)
            self.motion_complete.emit(self.target_x, self.target_y)
        except Exception as exc:
            self.motion_error.emit(str(exc))


class CameraThread(QThread):
    """Reads the DroidCam HTTP stream without blocking the GUI."""

    frame_ready = pyqtSignal(QImage)
    connection_changed = pyqtSignal(bool, str)
    fiducial_status_changed = pyqtSignal(str)

    def __init__(self, ip: str, port: int) -> None:
        super().__init__()
        self.url = f"http://{ip}:{port}/video"
        self._running = True
        self.fiducial_detection_enabled = True

    def stop(self) -> None:
        self._running = False
        self.wait(2000)

    def set_fiducial_detection_enabled(self, enabled: bool) -> None:
        self.fiducial_detection_enabled = enabled

    def run(self) -> None:
        camera = cv2.VideoCapture(self.url)
        ok, frame = camera.read()
        if not ok or frame is None:
            camera.release()
            self.connection_changed.emit(False, "Camera connection failed")
            return

        self.connection_changed.emit(True, f"Camera connected: {self.url}")
        while self._running:
            if frame is None:
                ok, frame = camera.read()
                if not ok:
                    self.connection_changed.emit(False, "Camera stream interrupted")
                    break

            display_frame = frame
            if self.fiducial_detection_enabled:
                pair = detect_fiducial_pair(frame)
                display_frame = draw_fiducial_overlay(frame, pair)
                if pair is None:
                    self.fiducial_status_changed.emit("Fiducials: searching")
                else:
                    midpoint = pair.midpoint
                    self.fiducial_status_changed.emit(
                        f"Fiducials found. Midpoint: {midpoint[0]:.0f}, {midpoint[1]:.0f} px. "
                        f"Angle: {pair.angle_degrees:.2f} deg."
                    )

            rgb = cv2.cvtColor(display_frame, cv2.COLOR_BGR2RGB)
            height, width, channels = rgb.shape
            image = QImage(rgb.data, width, height, channels * width, QImage.Format_RGB888).copy()
            self.frame_ready.emit(image)
            ok, frame = camera.read()
            if not ok:
                frame = None

        camera.release()


class PCBPrinterGUI(QMainWindow):
    """Control surface for PING/STATUS/MOVE firmware revision."""

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("PCB Printer Motion Control")
        self.setMinimumSize(680, 480)

        self.motion: Optional[MotionController] = None
        self.motion_thread: Optional[MotionThread] = None
        self.camera_thread: Optional[CameraThread] = None
        self.is_connected = False
        self.current_x = 0.0
        self.current_y = 0.0

        self._build_ui()
        logging.basicConfig(level=logging.INFO)
        QTimer.singleShot(0, self.connect_camera)

    def _build_ui(self) -> None:
        central = QWidget()
        self.setCentralWidget(central)
        layout = QHBoxLayout(central)

        camera_layout = QVBoxLayout()
        camera_group = QGroupBox("DroidCam")
        camera_group_layout = QVBoxLayout(camera_group)
        self.camera_label = QLabel("Connecting to DroidCam...")
        self.camera_label.setAlignment(Qt.AlignCenter)
        self.camera_label.setMinimumSize(640, 480)
        self.camera_label.setStyleSheet("background: #171717; color: #f0f0f0;")
        camera_group_layout.addWidget(self.camera_label)

        camera_connection_layout = QGridLayout()
        camera_connection_layout.addWidget(QLabel("WiFi IP"), 0, 0)
        self.camera_ip_input = QLineEdit("10.59.59.49")
        camera_connection_layout.addWidget(self.camera_ip_input, 0, 1)
        camera_connection_layout.addWidget(QLabel("Port"), 0, 2)
        self.camera_port_input = QSpinBox()
        self.camera_port_input.setRange(1, 65535)
        self.camera_port_input.setValue(4747)
        camera_connection_layout.addWidget(self.camera_port_input, 0, 3)
        self.camera_connect_button = QPushButton("Connect Camera")
        self.camera_connect_button.clicked.connect(self.connect_camera)
        camera_connection_layout.addWidget(self.camera_connect_button, 1, 1)
        self.camera_disconnect_button = QPushButton("Disconnect Camera")
        self.camera_disconnect_button.clicked.connect(self.disconnect_camera)
        self.camera_disconnect_button.setEnabled(False)
        camera_connection_layout.addWidget(self.camera_disconnect_button, 1, 2, 1, 2)
        self.fiducial_detection_checkbox = QCheckBox("Detect 2 fiducials")
        self.fiducial_detection_checkbox.setChecked(True)
        self.fiducial_detection_checkbox.toggled.connect(self.set_fiducial_detection_enabled)
        camera_connection_layout.addWidget(self.fiducial_detection_checkbox, 1, 0)
        camera_group_layout.addLayout(camera_connection_layout)
        camera_layout.addWidget(camera_group)
        layout.addLayout(camera_layout, 2)

        controls_layout = QVBoxLayout()

        connection_group = QGroupBox("Connection")
        connection_layout = QHBoxLayout(connection_group)
        connection_layout.addWidget(QLabel("Serial port"))
        self.port_combo = QComboBox()
        self._refresh_ports()
        connection_layout.addWidget(self.port_combo, 1)
        self.refresh_button = QPushButton("Refresh")
        self.refresh_button.clicked.connect(self._refresh_ports)
        connection_layout.addWidget(self.refresh_button)
        self.connect_button = QPushButton("Connect")
        self.connect_button.clicked.connect(self.connect_system)
        connection_layout.addWidget(self.connect_button)
        self.disconnect_button = QPushButton("Disconnect")
        self.disconnect_button.clicked.connect(self.disconnect_system)
        self.disconnect_button.setEnabled(False)
        connection_layout.addWidget(self.disconnect_button)
        controls_layout.addWidget(connection_group)

        position_group = QGroupBox("Position")
        position_layout = QGridLayout(position_group)
        position_layout.addWidget(QLabel("X"), 0, 0)
        self.x_position_label = QLabel("0.00 mm")
        self.x_position_label.setFont(QFont("Courier", 11, QFont.Bold))
        position_layout.addWidget(self.x_position_label, 0, 1)
        position_layout.addWidget(QLabel("Y"), 1, 0)
        self.y_position_label = QLabel("0.00 mm")
        self.y_position_label.setFont(QFont("Courier", 11, QFont.Bold))
        position_layout.addWidget(self.y_position_label, 1, 1)
        controls_layout.addWidget(position_group)

        move_group = QGroupBox("Move To")
        move_layout = QGridLayout(move_group)
        self.x_spinbox = self._coordinate_input()
        self.y_spinbox = self._coordinate_input()
        self.speed_spinbox = QDoubleSpinBox()
        self.speed_spinbox.setRange(5.0, 1000.0)
        self.speed_spinbox.setValue(20.0)
        self.speed_spinbox.setDecimals(1)
        self.speed_spinbox.setSingleStep(5.0)
        self.speed_spinbox.setSuffix(" F")
        move_layout.addWidget(QLabel("X target"), 0, 0)
        move_layout.addWidget(self.x_spinbox, 0, 1)
        move_layout.addWidget(QLabel("Y target"), 1, 0)
        move_layout.addWidget(self.y_spinbox, 1, 1)
        move_layout.addWidget(QLabel("Feed"), 2, 0)
        move_layout.addWidget(self.speed_spinbox, 2, 1)
        controls_layout.addWidget(move_group)

        self.move_button = QPushButton("Move")
        self.move_button.clicked.connect(self.move_to_position)
        self.move_button.setEnabled(False)
        self.move_button.setMinimumHeight(42)
        controls_layout.addWidget(self.move_button)

        self.status_label = QLabel("Select the controller port and connect.")
        self.status_label.setAlignment(Qt.AlignCenter)
        controls_layout.addWidget(self.status_label)
        controls_layout.addStretch()
        layout.addLayout(controls_layout, 1)

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
        ports = discover_ports()
        self.port_combo.clear()
        self.port_combo.addItems(ports or ["COM6"])
        index = self.port_combo.findText(selected)
        if index >= 0:
            self.port_combo.setCurrentIndex(index)

    def connect_system(self) -> None:
        port_name = self.port_combo.currentText()
        try:
            self.motion = MotionController(timeout_s=20.0)
            self.motion.connect(port_name)
            self.motion_thread = MotionThread(self.motion)
            self.motion_thread.motion_complete.connect(self.on_motion_complete)
            self.motion_thread.motion_error.connect(self.on_motion_error)
            self.current_x = self.current_y = 0.0
            self._set_position_labels()
            self.is_connected = True
            self._update_connection_ui()
            self.status_label.setText(f"Connected to {port_name}. Position origin set to 0.00, 0.00.")
        except Exception as exc:
            self.motion = None
            self.status_label.setText(f"Connection failed: {exc}")
            QMessageBox.critical(self, "Connection Error", str(exc))

    def connect_camera(self) -> None:
        self.disconnect_camera()
        self.camera_label.setText("Connecting to DroidCam...")
        self.camera_connect_button.setEnabled(False)
        self.camera_thread = CameraThread(
            self.camera_ip_input.text().strip(), self.camera_port_input.value()
        )
        self.camera_thread.frame_ready.connect(self.show_camera_frame)
        self.camera_thread.connection_changed.connect(self.on_camera_connection_changed)
        self.camera_thread.fiducial_status_changed.connect(self.on_fiducial_status_changed)
        self.camera_thread.start()

    def disconnect_camera(self) -> None:
        if self.camera_thread:
            self.camera_thread.stop()
            self.camera_thread = None
        self.camera_disconnect_button.setEnabled(False)
        self.camera_connect_button.setEnabled(True)

    def set_fiducial_detection_enabled(self, enabled: bool) -> None:
        if self.camera_thread:
            self.camera_thread.set_fiducial_detection_enabled(enabled)
        if not enabled:
            self.status_label.setText("Fiducial detection paused")

    def show_camera_frame(self, image: QImage) -> None:
        pixmap = QPixmap.fromImage(image).scaled(
            self.camera_label.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation
        )
        self.camera_label.setPixmap(pixmap)

    def on_camera_connection_changed(self, connected: bool, message: str) -> None:
        self.camera_connect_button.setEnabled(not connected)
        self.camera_disconnect_button.setEnabled(connected)
        self.camera_ip_input.setEnabled(not connected)
        self.camera_port_input.setEnabled(not connected)
        if not connected:
            self.camera_label.setText(message)
        self.status_label.setText(message)

    def on_fiducial_status_changed(self, message: str) -> None:
        self.status_label.setText(message)

    def disconnect_system(self) -> None:
        if self.motion_thread and self.motion_thread.isRunning():
            QMessageBox.warning(self, "Move in Progress", "Wait for the move to finish before disconnecting.")
            return
        if self.motion:
            self.motion.disconnect()
        self.motion = None
        self.motion_thread = None
        self.is_connected = False
        self._update_connection_ui()
        self.status_label.setText("Disconnected")

    def _update_connection_ui(self) -> None:
        self.connect_button.setEnabled(not self.is_connected)
        self.disconnect_button.setEnabled(self.is_connected)
        self.move_button.setEnabled(self.is_connected)
        self.port_combo.setEnabled(not self.is_connected)
        self.refresh_button.setEnabled(not self.is_connected)

    def move_to_position(self) -> None:
        if not self.motion_thread or self.motion_thread.isRunning():
            return
        target_x, target_y = self.x_spinbox.value(), self.y_spinbox.value()
        speed = self.speed_spinbox.value()
        distance = abs(target_x - self.current_x) + abs(target_y - self.current_y)
        # Firmware emits 100 pulses/mm, with a full pulse taking roughly 1/speed seconds.
        timeout_s = max(20.0, (distance * 100.0 / speed) + 15.0)
        self.motion_thread.set_target(target_x, target_y, speed, timeout_s)
        self.move_button.setEnabled(False)
        self.disconnect_button.setEnabled(False)
        self.status_label.setText(
            f"Moving to X={target_x:.3f} mm, Y={target_y:.3f} mm at F={speed:.1f}..."
        )
        self.motion_thread.start()

    def on_motion_complete(self, x: float, y: float) -> None:
        self.current_x, self.current_y = x, y
        self._set_position_labels()
        self.status_label.setText("Move complete")
        self.move_button.setEnabled(True)
        self.disconnect_button.setEnabled(True)

    def on_motion_error(self, error: str) -> None:
        logger.error("Motion error: %s", error)
        self.status_label.setText(f"Move failed: {error}")
        self.move_button.setEnabled(True)
        self.disconnect_button.setEnabled(True)

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
