from __future__ import annotations

import argparse

from marker.motion.controller import MotionController, discover_ports


def _list_ports() -> None:
    ports = discover_ports()
    if not ports:
        print("No serial ports discovered")
        return
    for port in ports:
        print(port)


def _ping_device(port_name: str, timeout_s: float) -> None:
    controller = MotionController(timeout_s=timeout_s)
    try:
        controller.connect(port_name)
        print(f"Ping successful: {controller.ping()}")
    except Exception as exc:  # pragma: no cover - CLI error path
        print(f"Connection or ping failed: {exc}")
    finally:
        controller.disconnect()


def main() -> None:
    parser = argparse.ArgumentParser(description="Marker motion controller tester")
    parser.add_argument("--list-ports", action="store_true", help="List serial ports")
    parser.add_argument("--port", type=str, default=None, help="Serial port to connect to")
    parser.add_argument("--ping", action="store_true", help="Send a PING command")
    parser.add_argument("--timeout", type=float, default=5.0, help="Serial timeout in seconds")
    args = parser.parse_args()

    if args.list_ports:
        _list_ports()
        return

    if args.port and args.ping:
        _ping_device(args.port, args.timeout)
        return

    if args.port:
        controller = MotionController(timeout_s=args.timeout)
        try:
            controller.connect(args.port)
            status = controller.get_status()
            print(f"Status: state={status.state} x={status.x} y={status.y}")
        except Exception as exc:  # pragma: no cover - CLI error path
            print(f"Could not connect to device: {exc}")
        finally:
            controller.disconnect()
        return

    parser.print_help()


if __name__ == "__main__":
    main()
