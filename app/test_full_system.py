"""
Complete System Integration Test for PCB Printer
Tests motion control, camera feedback, and GUI in sequence.
"""

import sys
import time
import logging
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent / "src"))

from marker.motion.controller import MotionController, discover_ports
from marker.motion.motion_with_feedback import MotionWithFeedback


def setup_logging():
    """Configure logging."""
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s'
    )
    return logging.getLogger(__name__)


logger = setup_logging()


def test_serial_connection(port: str = "COM6") -> bool:
    """Test serial connection to Arduino."""
    print("\n" + "="*60)
    print("TEST 1: Serial Connection")
    print("="*60)
    
    try:
        motion = MotionController()
        motion.connect(port)
        print(f"✓ Connected to {port}")
        
        # Test ping
        if motion.ping():
            print("✓ PING successful")
        else:
            print("✗ PING failed")
            return False
        
        # Get status
        status = motion.get_status()
        print(f"✓ Status retrieved:")
        print(f"  - State: {status.state}")
        print(f"  - X: {status.x:.2f} mm")
        print(f"  - Y: {status.y:.2f} mm")
        
        motion.disconnect()
        return True
        
    except Exception as e:
        print(f"✗ Serial connection failed: {e}")
        return False


def test_camera_connection(camera_ip: str = "10.59.59.49") -> bool:
    """Test camera connection."""
    print("\n" + "="*60)
    print("TEST 2: Camera Connection")
    print("="*60)
    
    try:
        from marker.motion.camera import CameraFeed
        
        camera = CameraFeed(camera_ip, 4747)
        if camera.connect():
            print(f"✓ Connected to DroidCam at {camera_ip}:4747")
            
            # Try to capture a frame
            frame = camera.get_frame()
            if frame is not None:
                h, w = frame.shape[:2]
                print(f"✓ Frame captured: {w}x{h} pixels")
                camera.release()
                return True
            else:
                print("✗ Failed to capture frame")
                return False
        else:
            print(f"✗ Failed to connect to camera at {camera_ip}")
            return False
            
    except Exception as e:
        print(f"✗ Camera connection failed: {e}")
        return False


def test_motion_with_feedback(port: str = "COM6", camera_ip: str = "10.59.59.49") -> bool:
    """Test integrated motion with camera feedback."""
    print("\n" + "="*60)
    print("TEST 3: Motion with Camera Feedback")
    print("="*60)
    
    try:
        # Create motion controller
        motion = MotionController()
        motion.connect(port)
        print(f"✓ Motion controller connected to {port}")
        
        # Create feedback system
        system = MotionWithFeedback(motion, camera_ip=camera_ip)
        
        if not system.camera.connected:
            print("⚠ Camera not connected (motion still works)")
        else:
            print(f"✓ Camera connected")
        
        # Test status
        status = motion.get_status()
        print(f"✓ Initial status: X={status.x:.2f}, Y={status.y:.2f}")
        
        # Test small motion
        print("\nTest motion: Moving X to 5mm...")
        system.move_to_with_feedback(5.0, 0.0, speed=30.0)
        
        status_after = motion.get_status()
        print(f"✓ After motion: X={status_after.x:.2f}, Y={status_after.y:.2f}")
        
        # Test snapshot if camera available
        if system.camera.connected:
            print("\nCapturing snapshot...")
            if system.capture_snapshot("test_snapshot.png"):
                print("✓ Snapshot saved: test_snapshot.png")
        
        system.disconnect()
        motion.disconnect()
        return True
        
    except Exception as e:
        print(f"✗ Motion test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def show_gui_instructions():
    """Show GUI launch instructions."""
    print("\n" + "="*60)
    print("NEXT STEP: Launch GUI Application")
    print("="*60)
    
    print("""
The complete PCB Printer control GUI is ready to use.

METHOD 1: Double-click batch file (Easiest)
  → Explorer: app\\start_gui.bat
  → Double-click and the GUI will launch

METHOD 2: Command line
  → cd C:\\Com_Printer\\app
  → python launch_gui.py

METHOD 3: Windows Start Menu
  → Create shortcut to: app\\start_gui.bat
  → Pin to Start Menu for quick access

FIRST TIME ONLY:
  → cd C:\\Com_Printer\\app
  → python setup_gui.py
  → This installs: PyQt5, OpenCV, numpy, pyserial

THEN:
  → GUI will open with connection settings
  → Serial port should auto-detect (COM6)
  → Camera IP should default to 10.59.59.49
  → Click [🔗 Connect]
  → See live camera feed with status overlay
  → Control motion with spinboxes and buttons
    """)


def main():
    """Run complete system test."""
    print("\n" + "="*70)
    print(" PCB PRINTER - COMPLETE SYSTEM INTEGRATION TEST")
    print("="*70)
    
    # Discover available ports
    print("\nSearching for available serial ports...")
    ports = discover_ports()
    if ports:
        print(f"Found ports: {ports}")
    else:
        print("No ports found. Trying COM6...")
    
    port = "COM6"
    camera_ip = "10.59.59.49"
    
    print(f"\nUsing:")
    print(f"  Serial Port: {port}")
    print(f"  Camera IP: {camera_ip}")
    
    # Run tests
    results = {}
    
    results['serial'] = test_serial_connection(port)
    results['camera'] = test_camera_connection(camera_ip)
    results['motion'] = test_motion_with_feedback(port, camera_ip)
    
    # Summary
    print("\n" + "="*60)
    print("TEST SUMMARY")
    print("="*60)
    
    all_passed = True
    for test_name, result in results.items():
        status = "✓ PASS" if result else "✗ FAIL"
        print(f"{test_name:20} {status}")
        if not result:
            all_passed = False
    
    if all_passed:
        print("\n✓ All tests passed!")
        show_gui_instructions()
        return 0
    else:
        print("\n⚠ Some tests failed. Check connections:")
        print("  - Arduino USB connected to COM6?")
        print("  - DroidCam running on S22?")
        print("  - Phone on same WiFi network?")
        return 1


if __name__ == "__main__":
    sys.exit(main())
