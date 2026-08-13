# Converter Marker

A two-axis PCB panel marking machine project with a Python laptop application and an Arduino-based motion controller.

This repository currently contains the Phase 1 and Phase 2 baseline:

- project skeleton and repo layout
- Arduino UNO PlatformIO project
- line-oriented serial protocol with command IDs
- Python serial discovery and connection code
- simulator-based testing without hardware
- protocol validation tests

## Repository Layout

```text
converter-marker/
├── README.md
├── .gitignore
├── docs/
│   ├── architecture.md
│   └── serial-protocol.md
├── firmware/
│   ├── platformio.ini
│   ├── include/
│   │   ├── config.h
│   │   └── protocol.h
│   └── src/
│       └── main.cpp
├── app/
│   ├── pyproject.toml
│   ├── src/
│   │   └── marker/
│   │       ├── __init__.py
│   │       ├── main.py
│   │       └── motion/
│   │           ├── __init__.py
│   │           ├── controller.py
│   │           ├── protocol.py
│   │           └── simulator.py
│   └── tests/
│       ├── test_protocol_parser.py
│       └── test_serial_controller.py
├── config/
│   └── machine.example.yaml
├── panel-definitions/
│   └── example-panel.yaml
├── logs/
└── docs/
```

## VS Code Setup

1. Install Visual Studio Code.
2. Install the Python extension.
3. Install the PlatformIO extension.
4. Open the repository root in VS Code.

## PlatformIO Installation

Use either the PlatformIO extension within VS Code or PlatformIO Core:

```bash
pip install platformio
```

Then verify:

```bash
pio --version
```

## Python Environment Setup

Use `uv` when available:

```bash
cd app
uv venv
uv pip install -e .
```

Or use the built-in virtual environment:

```bash
cd app
python -m venv .venv
. .venv\Scripts\activate
python -m pip install --upgrade pip
python -m pip install -e .
```

## Firmware Build and Upload

```bash
cd firmware
pio run
pio run -t upload
```

Monitor serial output:

```bash
pio device monitor
```

## Running the Python Application

```bash
cd app
python -m marker.main --list-ports
```

To ping a connected controller:

```bash
cd app
python -m marker.main --port COM3 --ping
```

## Running Tests

```bash
cd app
python -m pytest -q
```

## Serial Protocol Summary

The current implementation uses a line-oriented ASCII protocol. Example command:

```text
$ID=42 CMD=PING
```

Example response:

```text
@OK ID=42 CMD=PING
```

A full protocol specification is maintained in [docs/serial-protocol.md](docs/serial-protocol.md).

## Current Implementation Status

### Completed Features ✓
- Motor motion control with calibrated stepper drivers (400 steps/turn, 4mm/turn)
- Dual-axis motion (X/Y) with real-time position feedback
- Camera integration with live feed from DroidCam on Samsung S22
- Professional desktop GUI for motion control with camera overlay
- Snapshot capture and motion video recording
- Real-time motion status display with position overlay
- Emergency stop functionality
- Comprehensive test suite for all components

### GUI Application

The PCB Printer now includes a professional desktop control application with live camera feedback.

#### Quick Start

**Option 1: Batch File (Easiest for Windows)**
```bash
# Double-click this file in Explorer:
app\start_gui.bat
```

**Option 2: Command Line**
```bash
cd app
python launch_gui.py
```

**Option 3: Direct Module Execution**
```bash
cd C:\Com_Printer
python -m marker.gui.printer_control
```

#### First Time Setup
```bash
# Check dependencies and install missing packages
cd app
python setup_gui.py

# If manual install is needed:
pip install PyQt5 opencv-python numpy pyserial
```

#### GUI Features
- **Live Camera Feed**: Real-time video from DroidCam with motion status overlay
- **Motion Control**: Set X/Y target positions and speed
- **Position Display**: Live updates of current X/Y coordinates
- **Snapshots**: Capture and save PCB state photos
- **Video Recording**: Record motion execution for analysis
- **Emergency Stop**: Immediate halt with confirmation
- **Home Position**: Return to reference point
- **Status Monitoring**: Real-time machine state display

#### Hardware Requirements for GUI
- **Motion Controller**: Arduino UNO on COM6 (usually)
- **Stepper Drivers**: DM556 drivers for X and Y axes
- **Camera**: DroidCam app on Samsung S22 (same WiFi network)
- **Network**: Phone and laptop on same LAN (10.x.x.x subnet)

#### Hardware Calibration
- **Motor Type**: NEMA 17 stepper
- **Lead Screw Pitch**: 4 mm per turn
- **Stepper Resolution**: 400 pulses per turn (with 2x microstepping)
- **Position Resolution**: 0.01 mm per step = 100 steps/mm
- **X Axis Pins**: D3 (PUL), D2 (DIR)
- **Y Axis Pins**: D7 (PUL), D6 (DIR)
- **Enable Pin**: D8

See [docs/wiring.md](docs/wiring.md) for detailed hardware connections.

#### Camera Setup
1. Install DroidCam app on Samsung S22
2. Use the WiFi IP shown by DroidCam (currently 10.59.59.87), not the device IP
3. Ensure phone and laptop are on same WiFi network
4. Enter IP in GUI "Camera IP" field and click Connect

#### File Outputs
- Snapshots: `snapshot_YYYYMMDD_HHMMSS.png`
- Motion Videos: `motion_YYYYMMDD_HHMMSS.mp4`

### Remaining Work
- DataMatrix detection and alignment
- Print head/marker integration
- Automated calibration wizard
- Motion queue and macro recording
- Extended logging and analytics
- inventory communication
- panel path planning

Only the protocol layer and the serial transport baseline are implemented in this phase.
