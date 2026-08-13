import time

import pytest

from marker.motion.controller import (
    CommandExecutionError,
    MotionController,
    SerialConnectionError,
    discover_ports,
)
from marker.motion.simulator import SimulatedSerialPort


@pytest.fixture
def controller() -> MotionController:
    port = SimulatedSerialPort()
    controller = MotionController(port=port)
    controller.connect()
    return controller


def test_discover_ports_returns_list() -> None:
    ports = discover_ports()
    assert isinstance(ports, list)


def test_ping_round_trip(controller: MotionController) -> None:
    assert controller.ping() is True


def test_move_waits_for_done_response(controller: MotionController) -> None:
    controller.move_to(-10.0, 0.0, 20.0)


def test_move_serializes_selected_feed_rate(controller: MotionController) -> None:
    controller.move_to(0.0, -10.0, 75.0)
    assert controller.port.queued_commands()[-1] == "$ID=1 CMD=MOVE X=0.000 Y=-10.000 F=75.0\n"


def test_firmware_error_is_raised(controller: MotionController) -> None:
    with pytest.raises(CommandExecutionError, match="UNSUPPORTED_COMMAND"):
        controller.home()


def test_timeout_raises() -> None:
    port = SimulatedSerialPort(auto_respond=False)
    controller = MotionController(port=port)
    controller.connect()
    with pytest.raises(SerialConnectionError):
        controller.send_command("$ID=999 CMD=PING", timeout_s=0.01)


def test_disconnect_is_handled(controller: MotionController) -> None:
    controller.disconnect()
    assert controller.is_connected() is False


def test_connect_with_port_name_uses_real_serial_when_available(monkeypatch: pytest.MonkeyPatch) -> None:
    created = {}

    class FakeSerial:
        def __init__(self, port_name: str, baudrate: int, timeout: float):
            created["port_name"] = port_name
            created["baudrate"] = baudrate
            created["timeout"] = timeout
            self.is_open = True

        def close(self):
            self.is_open = False

    monkeypatch.setattr("marker.motion.controller.serial.Serial", FakeSerial)

    controller = MotionController()
    controller.connect("COM6")

    assert created["port_name"] == "COM6"
    assert created["baudrate"] == 115200
    assert controller.is_connected() is True
    controller.disconnect()
