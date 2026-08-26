from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from typing import Any

import serial  # type: ignore

from .protocol import ProtocolError, parse_command
from .simulator import SimulatedSerialPort


class SerialConnectionError(ConnectionError):
    """Raised when the serial channel is unavailable or times out."""


class CommandExecutionError(RuntimeError):
    """Raised when the controller rejects a command."""


@dataclass
class MachineStatus:
    state: str = "BOOT"
    x: float = 0.0
    y: float = 0.0


class MotionController:
    def __init__(self, port: Any | None = None, timeout_s: float = 5.0) -> None:
        self.port = port if port is not None else SimulatedSerialPort()
        self.timeout_s = timeout_s
        self._next_id = 1
        self._lock = threading.Lock()


    def connect(self, port_name: str | None = None) -> None:
        if port_name is not None:
            self.port = serial.Serial(port_name, 115200, timeout=self.timeout_s)
            return

        if isinstance(self.port, SimulatedSerialPort):
            self.port.open()
            return

        if self.port is None:
            raise SerialConnectionError("A serial port name is required for a real connection")

    def disconnect(self) -> None:
        if isinstance(self.port, SimulatedSerialPort):
            self.port.close()
            return
        if hasattr(self.port, "is_open") and self.port.is_open:
            self.port.close()

    def is_connected(self) -> bool:
        if isinstance(self.port, SimulatedSerialPort):
            return self.port.is_open()
        return hasattr(self.port, "is_open") and bool(self.port.is_open)

    def _next_command_id(self) -> int:
        with self._lock:
            value = self._next_id
            self._next_id += 1
            return value

    def send_command(self, line: str, timeout_s: float | None = None) -> str:
        if not self.is_connected():
            raise SerialConnectionError("Controller is not connected")

        timeout = self.timeout_s if timeout_s is None else timeout_s

        deadline = time.monotonic() + timeout
        with self._lock:
            try:
                if isinstance(self.port, SimulatedSerialPort):
                    self.port.write(line + "\n")
                else:
                    self.port.write((line + "\n").encode("ascii"))
            except (OSError, serial.SerialException) as exc:
                raise SerialConnectionError("Serial write failed") from exc

            while time.monotonic() < deadline:
                try:
                    if isinstance(self.port, SimulatedSerialPort):
                        response = self.port.readline(timeout_s=min(0.1, max(0.01, deadline - time.monotonic())))
                    else:
                        raw = self.port.readline()
                        response = raw.decode("ascii", errors="replace").strip() if raw else ""
                except (TimeoutError, serial.SerialException):
                    continue

                if not response or response.startswith("RX:") or response == "READY":
                    continue
                if response.startswith("@ERROR") or response.startswith("@ALARM"):
                    raise CommandExecutionError(response)
                if response.startswith("@DONE") or response.startswith("@STATUS"):
                    return response

        raise SerialConnectionError(f"Timed out waiting for completion of: {line}")

    def ping(self) -> bool:
        command_id = self._next_command_id()
        response = self.send_command(f"$ID={command_id} CMD=PING")
        return response.startswith("@DONE")

    def get_status(self) -> MachineStatus:
        command_id = self._next_command_id()
        response = self.send_command(f"$ID={command_id} CMD=STATUS")
        try:
            parsed = parse_command(response.replace("@STATUS ", "$ID=0 CMD=STATUS "))
        except ProtocolError:
            return MachineStatus()
        state = str(parsed.params.get("STATE", "BOOT"))
        x = float(parsed.params.get("X", 0.0))
        y = float(parsed.params.get("Y", 0.0))
        return MachineStatus(state=state, x=x, y=y)

    def home(self) -> None:
        self.send_command(f"$ID={self._next_command_id()} CMD=HOME")

    def move_to(
        self,
        x: float,
        y: float,
        speed: float,
        timeout_s: float | None = None,
        acceleration: float | None = None,
    ) -> None:
        acceleration_param = f" A={acceleration:.1f}" if acceleration is not None else ""
        self.send_command(
            f"$ID={self._next_command_id()} CMD=MOVE X={x:.3f} Y={y:.3f} F={speed:.1f}{acceleration_param}",
            timeout_s=timeout_s,
        )

    def jog(self, axis: str, distance: float, speed: float) -> None:
        self.send_command(f"$ID={self._next_command_id()} CMD=JOG AXIS={axis.upper()} DIST={distance:.3f} F={speed:.1f}")

    def trigger_print(self, duration_ms: int) -> None:
        self.send_command(f"$ID={self._next_command_id()} CMD=TRIGGER MS={duration_ms}")

    def stop(self) -> None:
        self.send_command(f"$ID={self._next_command_id()} CMD=STOP")

    def emergency_stop(self) -> None:
        self.send_command(f"$ID={self._next_command_id()} CMD=ESTOP")


def discover_ports() -> list[str]:
    try:
        import serial.tools.list_ports as list_ports

        return [port.device for port in list_ports.comports()]
    except Exception:
        return []
