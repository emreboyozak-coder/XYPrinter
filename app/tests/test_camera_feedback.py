"""
Test script for motion control with camera feedback.
Demonstrates live feed, snapshots, and motion video recording.
"""

import sys
import os
import logging
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from marker.motion.motion_with_feedback import MotionWithFeedback
from marker.motion.controller import MotionController


def setup_logging():
    """Configure logging for feedback system."""
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )


def run_camera_only_demo(camera_ip: str = "10.59.59.49"):
    """Test camera connection and live feed only."""
    print(f"\n=== Camera Connection Test ===")
    print(f"Connecting to DroidCam at {camera_ip}:4747...")
    
    from marker.motion.camera import CameraFeed, CameraViewer
    
    camera = CameraFeed(camera_ip, 4747)
    if camera.connect():
        print("✓ Camera connected successfully")
        print("Press 'q' to quit live feed...")
        viewer = CameraViewer(camera)
        frames = viewer.show_live_feed(max_frames=150)
        print(f"Displayed {frames} frames")
        camera.release()
        return True
    else:
        print("✗ Failed to connect to camera")
        return False


def run_motion_with_camera_demo(port: str = "COM6", camera_ip: str = "10.59.59.49"):
    """Test integrated motion control with camera feedback."""
    print(f"\n=== Motion with Camera Feedback Test ===")
    print(f"Serial port: {port}")
    print(f"Camera IP: {camera_ip}")
    
    motion = MotionController()
    try:
        motion.connect(port)
        print(f"✓ Motion controller connected to {port}")
    except Exception as e:
        print(f"✗ Failed to connect motion controller: {e}")
        return False
    
    # Create integrated system
    system = MotionWithFeedback(motion, camera_ip=camera_ip)
    
    if not system.camera.connected:
        print(f"✗ Failed to connect camera at {camera_ip}")
        motion.disconnect()
        return False
    
    print("✓ Camera connected")
    
    try:
        # Test 1: Live feed
        print("\nTest 1: Live camera feed (30 frames)...")
        frames = system.display_live_feed(max_frames=30)
        print(f"✓ Captured {frames} frames")
        
        # Test 2: Snapshot
        print("\nTest 2: Capturing snapshot...")
        snapshot_path = "pcb_snapshot.png"
        if system.capture_snapshot(snapshot_path):
            print(f"✓ Snapshot saved: {snapshot_path}")
            if os.path.exists(snapshot_path):
                size = os.path.getsize(snapshot_path) / 1024
                print(f"  File size: {size:.1f} KB")
        
        # Test 3: Motion with feedback
        print("\nTest 3: Testing motion with camera feedback...")
        status_before = motion.get_status()
        print(f"Status before: X={status_before.x:.2f}mm, Y={status_before.y:.2f}mm")
        
        print("Starting continuous capture...")
        system.start_continuous_capture()
        
        print("Moving to X=20mm, Y=10mm...")
        system.move_to_with_feedback(20.0, 10.0, 30.0)
        
        system.stop_continuous_capture()
        
        status_after = motion.get_status()
        print(f"Status after: X={status_after.x:.2f}mm, Y={status_after.y:.2f}mm")
        print("✓ Motion completed with camera feedback")
        
        print("\n=== All Tests Passed ===")
        return True
        
    except Exception as e:
        print(f"✗ Test error: {e}")
        import traceback
        traceback.print_exc()
        return False
        
    finally:
        system.disconnect()
        motion.disconnect()


def main():
    """Run tests."""
    setup_logging()
    
    # Try to find serial port
    from marker.motion.controller import discover_ports
    
    print("=" * 50)
    print("PCB Printer: Motion + Camera Feedback Test Suite")
    print("=" * 50)
    
    available_ports = discover_ports()
    print(f"\nAvailable serial ports: {available_ports}")
    
    # Test camera only first
    camera_ok = run_camera_only_demo()
    
    if not camera_ok:
        print("\n⚠ Camera test failed. Skipping motion tests.")
        return 1
    
    # Test motion with camera
    port = "COM6" if "COM6" in available_ports else (available_ports[0] if available_ports else "COM6")
    motion_ok = run_motion_with_camera_demo(port=port)
    
    return 0 if motion_ok else 1


if __name__ == "__main__":
    sys.exit(main())
