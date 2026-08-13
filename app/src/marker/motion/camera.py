"""
Camera module for live video feed from DroidCam IP camera.
Connects to DroidCam stream running on mobile device.
"""

import cv2
import logging
from typing import Optional, Tuple
import numpy as np

logger = logging.getLogger(__name__)


class CameraFeed:
    """Manages connection and frame capture from DroidCam IP camera."""
    
    def __init__(self, ip: str, port: int = 4747):
        """
        Initialize camera connection.
        
        Args:
            ip: WiFi IP address shown by DroidCam (e.g., '10.59.59.49')
            port: DroidCam port (default 4747)
        """
        self.ip = ip
        self.port = port
        # DroidCam HTTP stream URL
        self.url = f"http://{ip}:{port}/video"
        self.cap: Optional[cv2.VideoCapture] = None
        self.connected = False
        self.frame_count = 0
        
    def connect(self) -> bool:
        """
        Connect to DroidCam stream.
        
        Returns:
            True if connection successful, False otherwise
        """
        try:
            logger.info(f"Connecting to DroidCam at {self.url}...")
            self.cap = cv2.VideoCapture(self.url)
            
            # Try to read one frame to verify connection
            ret, frame = self.cap.read()
            if ret:
                self.connected = True
                logger.info(f"Connected to DroidCam. Frame size: {frame.shape}")
                return True
            else:
                logger.error("Failed to read frame from DroidCam")
                self.cap.release()
                self.cap = None
                return False
                
        except Exception as e:
            logger.error(f"Error connecting to DroidCam: {e}")
            return False
    
    def get_frame(self) -> Optional[np.ndarray]:
        """
        Capture a frame from the camera.
        
        Returns:
            Frame as numpy array, or None if failed
        """
        if not self.connected or self.cap is None:
            return None
            
        try:
            ret, frame = self.cap.read()
            if ret:
                self.frame_count += 1
                return frame
            else:
                logger.warning("Failed to read frame from DroidCam")
                return None
        except Exception as e:
            logger.error(f"Error reading frame: {e}")
            return None
    
    def release(self):
        """Close camera connection."""
        if self.cap is not None:
            self.cap.release()
            self.connected = False
            logger.info(f"Camera disconnected. Frames captured: {self.frame_count}")
    
    def __enter__(self):
        """Context manager entry."""
        self.connect()
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit."""
        self.release()


class CameraViewer:
    """Display live camera feed in OpenCV window."""
    
    def __init__(self, camera: CameraFeed, window_name: str = "PCB Printer Camera"):
        """
        Initialize viewer.
        
        Args:
            camera: CameraFeed instance
            window_name: Name of display window
        """
        self.camera = camera
        self.window_name = window_name
    
    def show_live_feed(self, max_frames: Optional[int] = None) -> int:
        """
        Display live camera feed.
        Press 'q' to quit.
        
        Args:
            max_frames: Maximum frames to display (None = infinite)
            
        Returns:
            Number of frames displayed
        """
        if not self.camera.connected:
            logger.error("Camera not connected")
            return 0
        
        frame_count = 0
        logger.info(f"Starting live feed ({max_frames} frames max if set)...")
        
        while True:
            frame = self.camera.get_frame()
            if frame is None:
                logger.error("Failed to get frame")
                break
            
            # Display frame
            cv2.imshow(self.window_name, frame)
            frame_count += 1
            
            # Check for quit key
            if cv2.waitKey(1) & 0xFF == ord('q'):
                logger.info("User quit")
                break
            
            # Check frame limit
            if max_frames and frame_count >= max_frames:
                logger.info(f"Reached frame limit: {max_frames}")
                break
        
        cv2.destroyAllWindows()
        return frame_count


def main():
    """Test camera connection and display feed."""
    import sys
    
    # Default DroidCam settings
    ip = "10.59.59.49"
    port = 4747
    
    if len(sys.argv) > 1:
        ip = sys.argv[1]
    if len(sys.argv) > 2:
        port = int(sys.argv[2])
    
    logging.basicConfig(level=logging.INFO)
    
    # Connect and show feed
    with CameraFeed(ip, port) as camera:
        if camera.connected:
            viewer = CameraViewer(camera)
            viewer.show_live_feed()
        else:
            print("Failed to connect to camera")
            sys.exit(1)


if __name__ == "__main__":
    main()
