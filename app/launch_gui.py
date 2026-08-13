"""
PCB Printer GUI Launcher
Run this to start the control application.
"""

import sys
import os
from pathlib import Path

# Add src to path so 'marker' module can be found
app_src_dir = Path(__file__).parent / "src"
sys.path.insert(0, str(app_src_dir))

if __name__ == "__main__":
    try:
        from marker.gui.printer_control import main
        main()
    except ImportError as e:
        print(f"Import Error: {e}")
        print("\nMake sure you have installed the required packages:")
        print("  pip install PyQt5 opencv-python numpy pyserial")
        sys.exit(1)
    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
