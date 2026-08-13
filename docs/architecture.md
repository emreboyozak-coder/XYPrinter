# Architecture

The project is deliberately split into two independent layers.

## Firmware layer

The Arduino firmware is responsible only for low-level machine I/O and motion execution. It receives a high-level command stream over USB serial and performs a narrow set of actions such as acknowledging commands, reporting status, and handling safe stop semantics.

This layer intentionally does not manage:

- camera calibration
- PCB definitions
- DataMatrix or QR generation
- printer communication
- inventory communication
- job orchestration

## Laptop layer

The Python application owns scheduling, safety policy, calibration, and workflow orchestration. It is responsible for serial communication with the controller, validation of replies, and the user interface enforcement.

This separation keeps motion execution deterministic and avoids unbounded software timing issues on Windows.
