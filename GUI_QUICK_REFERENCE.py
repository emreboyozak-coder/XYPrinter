"""
PCB Printer GUI - Quick Reference Card
"""

# ============================================================================
# PCB PRINTER CONTROL - QUICK START GUIDE
# ============================================================================

# START THE APPLICATION
# ============================================================================
# Windows: Double-click this file
#   app\start_gui.bat

# Or command line:
#   cd C:\Com_Printer\app
#   python launch_gui.py

# Or direct:
#   python -m marker.gui.printer_control


# CONNECTION CHECKLIST
# ============================================================================
# Before clicking "Connect":
# [ ] Arduino UNO connected via USB (usually COM6)
# [ ] DroidCam app running on Samsung S22
# [ ] Phone on same WiFi as laptop
# [ ] Note the WiFi IP from DroidCam (currently 10.59.59.87)


# INTERFACE LAYOUT
# ============================================================================
#
# +-------------------------------------------+---------------------------+
# |                                           |                           |
# |       LIVE CAMERA FEED                    |   CONTROLS                |
# |       (with status overlay)               |                           |
# |                                           |  📡 Connection            |
# |                                           |  - Serial Port: COM6       |
# |                                           |  - Camera IP: 10.133...   |
# |                                           |  [Connect] [Disconnect]  |
# |                                           |                           |
# |                                           |  📍 Status                |
# |  X=10.00mm Y=20.50mm State=IDLE           |  - State: IDLE            |
# |                                           |  - X: 10.00 mm            |
# |                                           |  - Y: 20.50 mm            |
# |                                           |                           |
# |                                           |  🎮 Motion                |
# |                                           |  - Target X: [ ] mm       |
# |                                           |  - Target Y: [ ] mm       |
# |                                           |  - Speed: [ ] mm/min      |
# |                                           |                           |
# |                                           |  🔘 Actions               |
# |                                           |  [▶ Move] [🏠 Home]      |
# | [📷 Snapshot] [🎥 Record Motion]         |  [⏹ Stop] [🛑 ESTOP]     |
# +-------------------------------------------+---------------------------+


# TYPICAL WORKFLOW
# ============================================================================

# 1. CONNECT
#    - Select serial port (COM6)
#    - Enter camera IP (10.59.59.87)
#    - Click [🔗 Connect]
#    - Wait for camera feed to appear

# 2. CONTROL
#    - Enter target X position (mm)
#    - Enter target Y position (mm)
#    - Set speed (mm/min)
#    - Click [▶ Move to Position]
#    - Watch camera feed during motion
#    - Position updates in real-time

# 3. CAPTURE
#    - [📷 Snapshot] - Save PCB photo
#    - [🎥 Record Motion] - Record video during motion

# 4. EMERGENCY
#    - [⏹ Stop] - Gentle stop
#    - [🛑 ESTOP] - Hard stop (requires confirmation)

# 5. DISCONNECT
#    - Click [🔌 Disconnect]


# HARDWARE CALIBRATION INFO
# ============================================================================
# Motor: NEMA 17 stepper
# Lead screw: 4 mm per turn
# Resolution: 400 steps per turn
# Translation: 0.01 mm per step = 100 steps/mm
# 
# X Axis: D3=PUL, D2=DIR
# Y Axis: D7=PUL, D6=DIR
# Enable: D8


# KEYBOARD SHORTCUTS
# ============================================================================
# Alt+F4     - Close application
# Q (in camera) - Quit live feed


# OUTPUT FILES
# ============================================================================
# Snapshots:    snapshot_YYYYMMDD_HHMMSS.png
# Videos:       motion_YYYYMMDD_HHMMSS.mp4
# Location:     Current working directory (C:\Com_Printer\app by default)


# TROUBLESHOOTING
# ============================================================================

# "Camera shows black screen"
# → Check DroidCam is running on S22
# → Verify camera IP (see DroidCam app)
# → Restart DroidCam app
# → Check WiFi connection

# "Motion doesn't execute"
# → Check serial port selection
# → Verify Arduino USB connection
# → Try [🏠 Home] first
# → Check motor power supply

# "Position not updating"
# → Check serial connection
# → Verify firmware upload
# → Confirm motor calibration (400 steps/turn)

# "Application won't start"
# → Run: pip install PyQt5 opencv-python numpy pyserial
# → Check Python version (3.8+): python --version
# → Try running setup_gui.py first


# MOTOR CONTROL LIMITS
# ============================================================================
# X Axis Range: -1000 to +1000 mm
# Y Axis Range: -1000 to +1000 mm
# Speed Range: 1 to 200 mm/min


# STATUS MESSAGES
# ============================================================================
# 🔵 Blue    = Information
# 🟠 Orange  = In progress
# 🟢 Green   = Success
# 🔴 Red     = Error


# ADVANCED USAGE - PYTHON CODE
# ============================================================================
#
# from marker.motion.controller import MotionController
# from marker.motion.motion_with_feedback import MotionWithFeedback
#
# # Connect
# motion = MotionController()
# motion.connect("COM6")
# system = MotionWithFeedback(motion, camera_ip="10.59.59.87")
#
# # Live feed
# system.display_live_feed()
#
# # Snapshot
# system.capture_snapshot("pcb_state.png")
#
# # Motion with recording
# system.record_motion_video("motion.mp4", x=20.0, y=10.0, speed=15.0)
#
# # Cleanup
# system.disconnect()
# motion.disconnect()


# SUPPORT & DOCUMENTATION
# ============================================================================
# GUI Docs:              app/gui-application.md (in repository memory)
# Hardware Wiring:       docs/wiring.md
# Serial Protocol:       docs/serial-protocol.md
# Main README:           README.md
# Motor Calibration:     memory/repo/motor-calibration.md
# Camera Setup:          memory/repo/camera-setup.md


print(__doc__)
