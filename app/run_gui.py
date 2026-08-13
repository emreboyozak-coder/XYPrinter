#!/usr/bin/env python3
"""
Direct Python launcher for PCB Printer GUI
No batch file dependencies - pure Python startup
"""

import sys
import os
import subprocess
from pathlib import Path


def find_python():
    """Find Python executable on the system."""
    # Check common Python locations
    possible_paths = [
        sys.executable,  # Current Python
        r"C:\Users\Emre Boy\AppData\Local\Microsoft\WindowsApps\python3.exe",
        r"C:\Users\Emre Boy\AppData\Local\Microsoft\WindowsApps\python.exe",
    ]
    
    for python_path in possible_paths:
        if python_path and Path(python_path).exists():
            return python_path
    
    return None


def main():
    """Launch GUI with proper Python."""
    print("="*60)
    print("PCB Printer Control GUI")
    print("="*60)
    print()
    
    # Get app directory
    app_dir = Path(__file__).parent
    os.chdir(app_dir)
    
    print(f"App directory: {app_dir}")
    print()
    
    # Run setup check
    print("Checking dependencies...")
    try:
        result = subprocess.run(
            [sys.executable, "setup_gui.py"],
            capture_output=False
        )
        if result.returncode != 0:
            print("\nSetup check failed.")
            print("Please run: python -m pip install PyQt5 opencv-python numpy pyserial")
            sys.exit(1)
    except Exception as e:
        print(f"Error running setup: {e}")
        sys.exit(1)
    
    # Launch GUI
    print("\nLaunching GUI application...")
    try:
        subprocess.run([sys.executable, "launch_gui.py"])
    except Exception as e:
        print(f"Error launching GUI: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
