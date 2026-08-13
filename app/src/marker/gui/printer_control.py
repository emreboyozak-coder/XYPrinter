"""Desktop control for the verified two-axis serial motion workflow."""

from __future__ import annotations

import logging
import sys
from typing import Optional

from PyQt5 import QtWidgets
from PyQt5.QtCore import Qt, QThread, pyqtSignal
from PyQt5.QtGui import QFont
from PyQt5.QtWidgets import (
    QComboBox,
    QDoubleSpinBox,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from marker.motion.controller import MotionController, discover_ports

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


class PCBPrinterGUI(QMainWindow):
    """Control surface for PING/STATUS/MOVE firmware revision."""

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("PCB Printer Motion Control")
        self.setMinimumSize(680, 480)

        self.motion: Optional[MotionController] = None
        self.motion_thread: Optional[MotionThread] = None
        self.is_connected = False
        self.current_x = 0.0
        self.current_y = 0.0

        self._build_ui()
        logging.basicConfig(level=logging.INFO)

    def _build_ui(self) -> None:
        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)

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
        layout.addWidget(connection_group)

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
        layout.addWidget(position_group)

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
        layout.addWidget(move_group)

        self.move_button = QPushButton("Move")
        self.move_button.clicked.connect(self.move_to_position)
        self.move_button.setEnabled(False)
        self.move_button.setMinimumHeight(42)
        layout.addWidget(self.move_button)

        self.status_label = QLabel("Select the controller port and connect.")
        self.status_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.status_label)
        layout.addStretch()

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
        event.accept()


def main() -> None:
    app = QtWidgets.QApplication(sys.argv)
    window = PCBPrinterGUI()
    window.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
