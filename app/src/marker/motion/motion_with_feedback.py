"""
Integrated motion controller with camera feedback system.
Combines stepper motor control with real-time video feedback from DroidCam.
"""

import threading
import logging
from dataclasses import dataclass
from typing import Optional, Callable

import cv2
import numpy as np

from .controller import MotionController, MachineStatus
from .camera import CameraFeed

logger = logging.getLogger(__name__)


@dataclass
class MotionWithFeedback:
    """Integrated motion control with camera feedback."""
    
    def __init__(
        self,
        motion: MotionController,
        camera_ip: str = "10.59.59.49",
        camera_port: int = 4747,
        auto_connect_camera: bool = True
    ):
        """
        Initialize motion controller with camera feedback.
        
        Args:
            motion: MotionController instance
            camera_ip: DroidCam IP address
            camera_port: DroidCam port (default 4747)
            auto_connect_camera: Connect to camera on init
        """
        self.motion = motion
        self.camera = CameraFeed(camera_ip, camera_port)
        self.camera_thread: Optional[threading.Thread] = None
        self.recording = False
        self.frame_buffer: Optional[np.ndarray] = None
        self.motion_callbacks: list[Callable] = []
        
        if auto_connect_camera:
            self.connect_camera()
    
    def connect_camera(self) -> bool:
        """Connect to DroidCam stream."""
        return self.camera.connect()
    
    def get_latest_frame(self) -> Optional[np.ndarray]:
        """Get the most recent camera frame."""
        return self.frame_buffer
    
    def start_continuous_capture(self) -> None:
        """Start background thread to capture frames continuously."""
        if self.camera_thread is not None and self.camera_thread.is_alive():
            logger.warning("Capture already running")
            return
        
        self.recording = True
        self.camera_thread = threading.Thread(target=self._capture_loop, daemon=True)
        self.camera_thread.start()
        logger.info("Started continuous camera capture")
    
    def stop_continuous_capture(self) -> None:
        """Stop background frame capture."""
        self.recording = False
        if self.camera_thread:
            self.camera_thread.join(timeout=2.0)
        logger.info("Stopped camera capture")
    
    def _capture_loop(self) -> None:
        """Background thread loop for frame capture."""
        while self.recording:
            frame = self.camera.get_frame()
            if frame is not None:
                self.frame_buffer = frame
            else:
                logger.warning("Failed to capture frame")
    
    def add_motion_callback(self, callback: Callable) -> None:
        """Register a callback to be called before/after motion."""
        self.motion_callbacks.append(callback)
    
    def move_to_with_feedback(self, x: float, y: float, speed: float) -> None:
        """
        Move to position and capture frames during motion.
        
        Args:
            x: Target X position in mm
            y: Target Y position in mm
            speed: Feed rate
        """
        for callback in self.motion_callbacks:
            try:
                callback("start", x, y)
            except Exception as e:
                logger.error(f"Callback error: {e}")
        
        try:
            self.motion.move_to(x, y, speed)
            logger.info(f"Moved to X={x:.2f}, Y={y:.2f}")
        except Exception as e:
            logger.error(f"Motion error: {e}")
            raise
        
        for callback in self.motion_callbacks:
            try:
                callback("complete", x, y)
            except Exception as e:
                logger.error(f"Callback error: {e}")
    
    def capture_snapshot(self, filename: str) -> bool:
        """
        Capture and save a single frame.
        
        Args:
            filename: Path to save image
            
        Returns:
            True if successful
        """
        frame = self.camera.get_frame()
        if frame is None:
            logger.error("No frame available")
            return False
        
        try:
            success = cv2.imwrite(filename, frame)
            if success:
                logger.info(f"Snapshot saved: {filename}")
            return success
        except Exception as e:
            logger.error(f"Failed to save snapshot: {e}")
            return False
    
    def record_motion_video(
        self,
        output_file: str,
        x: float,
        y: float,
        speed: float,
        fps: int = 10
    ) -> bool:
        """
        Record video while moving to target position.
        
        Args:
            output_file: Output video file path
            x: Target X position
            y: Target Y position
            speed: Feed rate
            fps: Video frames per second
            
        Returns:
            True if successful
        """
        if not self.camera.connected:
            logger.error("Camera not connected")
            return False
        
        # Get frame to determine resolution
        sample_frame = self.camera.get_frame()
        if sample_frame is None:
            logger.error("Cannot get sample frame for video setup")
            return False
        
        h, w = sample_frame.shape[:2]
        fourcc = cv2.VideoWriter_fourcc(*'mp4v')
        writer = cv2.VideoWriter(output_file, fourcc, fps, (w, h))
        
        try:
            self.recording = True
            frames_written = 0
            
            # Start motion in background thread
            motion_thread = threading.Thread(
                target=self.motion.move_to,
                args=(x, y, speed)
            )
            motion_thread.start()
            
            # Capture frames while motion is happening
            while self.recording and motion_thread.is_alive():
                frame = self.camera.get_frame()
                if frame is not None:
                    writer.write(frame)
                    frames_written += 1
            
            # Wait for motion to complete
            motion_thread.join(timeout=30.0)
            
            # Capture a few more frames after motion stops
            for _ in range(fps * 2):
                frame = self.camera.get_frame()
                if frame is not None:
                    writer.write(frame)
                    frames_written += 1
            
            writer.release()
            self.recording = False
            logger.info(f"Video saved: {output_file} ({frames_written} frames)")
            return True
            
        except Exception as e:
            logger.error(f"Video recording error: {e}")
            writer.release()
            return False
    
    def display_live_feed(self, max_frames: Optional[int] = None) -> int:
        """
        Display live camera feed in window.
        Press 'q' to quit.
        
        Args:
            max_frames: Max frames to display (None = infinite)
            
        Returns:
            Number of frames displayed
        """
        if not self.camera.connected:
            logger.error("Camera not connected")
            return 0
        
        frames = 0
        logger.info("Live feed window opened. Press 'q' to quit.")
        
        while True:
            frame = self.camera.get_frame()
            if frame is None:
                logger.error("Failed to get frame")
                break
            
            # Add status info overlay
            status = self.motion.get_status()
            text = f"X={status.x:.2f}mm Y={status.y:.2f}mm State={status.state}"
            cv2.putText(frame, text, (10, 30), cv2.FONT_HERSHEY_SIMPLEX,
                       0.7, (0, 255, 0), 2)
            
            cv2.imshow("PCB Printer - Live Feedback", frame)
            frames += 1
            
            if cv2.waitKey(1) & 0xFF == ord('q'):
                break
            
            if max_frames and frames >= max_frames:
                break
        
        cv2.destroyAllWindows()
        return frames
    
    def disconnect(self) -> None:
        """Clean up resources."""
        self.stop_continuous_capture()
        self.camera.release()
        logger.info("Motion with feedback system disconnected")


def main():
    """Demo: Motion control with camera feedback."""
    import sys
    
    logging.basicConfig(level=logging.INFO)
    
    # Create motion controller
    motion = MotionController()
    motion.connect("COM6")
    
    # Create integrated controller
    system = MotionWithFeedback(motion, auto_connect_camera=True)
    
    if not system.camera.connected:
        print("Failed to connect to camera")
        motion.disconnect()
        sys.exit(1)
    
    try:
        print("Showing live camera feed with motion status overlay...")
        print("Press 'q' to stop.")
        system.display_live_feed(max_frames=300)
        
        print("\nTest: Moving X to 10mm with camera feedback...")
        system.start_continuous_capture()
        system.move_to_with_feedback(10.0, 0.0, 20.0)
        system.stop_continuous_capture()
        
    finally:
        system.disconnect()
        motion.disconnect()


if __name__ == "__main__":
    main()
