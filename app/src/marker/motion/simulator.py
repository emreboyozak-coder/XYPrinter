from __future__ import annotations

import threading
import time
from collections import deque
from typing import Deque


class SimulatedSerialPort:
    """Minimal serial-like port used for tests without hardware."""

    def __init__(self, auto_respond: bool = True) -> None:
        self._connected = False
        self._write_buffer: Deque[str] = deque()
        self._read_queue: Deque[str] = deque()
        self._write_lock = threading.Lock()
        self._read_lock = threading.Lock()
        self._status_state = "IDLE"
        self._status_x = 0.0
        self._status_y = 0.0
        self._auto_respond = auto_respond

    def open(self) -> None:
        self._connected = True

    def close(self) -> None:
        self._connected = False

    def is_open(self) -> bool:
        return self._connected

    def _compose_response(self, message: str) -> str:
        response = message.strip()
        if not response:
            return "@ERROR ID=-1 CODE=EMPTY_MESSAGE\n"
        if not response.startswith("$"):
            return "@ERROR ID=-1 CODE=INVALID_COMMAND\n"
        try:
            parts = response[1:].split()
            if len(parts) < 2:
                return "@ERROR ID=-1 CODE=INVALID_COMMAND\n"
            id_part = parts[0]
            cmd_part = parts[1]
            if not id_part.startswith("ID="):
                return "@ERROR ID=-1 CODE=INVALID_COMMAND\n"
            if not cmd_part.startswith("CMD="):
                return "@ERROR ID=-1 CODE=INVALID_COMMAND\n"
            cmd_name = cmd_part.split("=", 1)[1].upper()
            cmd_id = id_part.split("=", 1)[1]
            if cmd_name == "PING":
                return f"@OK ID={cmd_id} CMD=PING\n@DONE ID={cmd_id} CMD=PING\n"
            if cmd_name == "STATUS":
                return f"@STATUS STATE={self._status_state} X={self._status_x:.3f} Y={self._status_y:.3f}\n"
            if cmd_name == "MOVE":
                params = {}
                for token in parts[2:]:
                    if "=" in token:
                        key, value = token.split("=", 1)
                        params[key.upper()] = value
                self._status_x = float(params.get("X", self._status_x))
                self._status_y = float(params.get("Y", self._status_y))
                return f"@OK ID={cmd_id} CMD=MOVE\n@DONE ID={cmd_id} CMD=MOVE\n"
            return f"@ERROR ID={cmd_id} CODE=UNSUPPORTED_COMMAND\n"
        except Exception:
            return "@ERROR ID=-1 CODE=INVALID_COMMAND\n"

    def write(self, data: bytes | str) -> int:
        if not self._connected:
            raise OSError("Serial port is not connected")
        payload = data.decode("ascii") if isinstance(data, (bytes, bytearray)) else data
        with self._write_lock:
            self._write_buffer.append(payload)
        message = payload.strip()
        if self._auto_respond and message:
            with self._read_lock:
                self._read_queue.extend(self._compose_response(message).splitlines(keepends=True))
        return len(payload)

    def readline(self, timeout_s: float = 0.1) -> str:
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            with self._read_lock:
                if self._read_queue:
                    return self._read_queue.popleft()
            time.sleep(0.01)
        raise TimeoutError("No response available from simulator")

    def enqueue_response(self, response: str) -> None:
        with self._read_lock:
            self._read_queue.append(response if response.endswith("\n") else response + "\n")

    def queued_commands(self) -> list[str]:
        with self._write_lock:
            return list(self._write_buffer)

    def consume_commands(self) -> list[str]:
        with self._write_lock:
            commands = list(self._write_buffer)
            self._write_buffer.clear()
        return commands
