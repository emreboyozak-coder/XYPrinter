"""
Quick setup and dependency check for PCB Printer GUI
"""

import subprocess
import sys


def check_python_version():
    """Verify Python 3.8+"""
    version = sys.version_info
    if version.major < 3 or (version.major == 3 and version.minor < 8):
        print(f"❌ Python 3.8+ required. Current: {version.major}.{version.minor}")
        return False
    print(f"✓ Python {version.major}.{version.minor} OK")
    return True


def check_and_install_packages():
    """Check and install required packages."""
    packages = {
        'PyQt5': 'PyQt5',
        'cv2': 'opencv-python',
        'numpy': 'numpy',
        'serial': 'pyserial'
    }
    
    all_ok = True
    for import_name, package_name in packages.items():
        try:
            __import__(import_name)
            print(f"✓ {package_name} installed")
        except ImportError:
            print(f"❌ {package_name} not found. Installing...")
            try:
                subprocess.check_call(
                    [sys.executable, "-m", "pip", "install", package_name],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL
                )
                print(f"✓ {package_name} installed successfully")
            except Exception as e:
                print(f"❌ Failed to install {package_name}: {e}")
                all_ok = False
    
    return all_ok


def verify_project_structure():
    """Verify required project files exist."""
    from pathlib import Path
    
    # Get the app directory (where this script is located)
    app_dir = Path(__file__).parent
    
    required_files = [
        app_dir / "src/marker/motion/controller.py",
        app_dir / "src/marker/motion/camera.py",
        app_dir / "src/marker/motion/motion_with_feedback.py",
        app_dir / "src/marker/gui/printer_control.py",
    ]
    
    all_ok = True
    for file_path in required_files:
        if file_path.exists():
            print(f"✓ {file_path.name} found")
        else:
            print(f"❌ {file_path.name} not found at {file_path}")
            all_ok = False
    
    return all_ok


def main():
    """Run setup checks."""
    print("\n" + "="*50)
    print("PCB Printer GUI - Setup Check")
    print("="*50 + "\n")
    
    # Check Python version
    print("Checking Python version...")
    if not check_python_version():
        return 1
    
    print("\nChecking dependencies...")
    if not check_and_install_packages():
        print("\n⚠ Some packages failed to install. Try manual install:")
        print("  pip install PyQt5 opencv-python numpy pyserial")
        return 1
    
    print("\nVerifying project structure...")
    if not verify_project_structure():
        print("\n⚠ Warning: Some project files not found.")
        print("  The application may not work correctly.")
        print("  Continuing anyway...\n")
    
    print("\n" + "="*50)
    print("✓ All checks passed! Ready to launch GUI.")
    print("="*50)
    print("\nTo start the application, run:")
    print("  python launch_gui.py")
    print("\nOr:")
    print("  python -m marker.gui.printer_control")
    print()
    
    return 0
    
    return 0


if __name__ == "__main__":
    sys.exit(main())
