@echo off
REM PCB Printer GUI - Simplified Launcher
REM This version is optimized for Windows Store Python

setlocal enabledelayedexpansion

echo ============================================================
echo PCB Printer Control GUI
echo ============================================================
echo.

REM Method 1: Try python3 from PATH
python3 --version >nul 2>&1
if errorlevel 0 (
    echo Starting application...
    python3 run_gui.py
    goto end
)

REM Method 2: Try python from PATH  
python --version >nul 2>&1
if errorlevel 0 (
    echo Starting application...
    python run_gui.py
    goto end
)

REM Method 3: Show installation instructions
echo.
echo Python not found in PATH
echo.
echo QUICK FIX - Option A (Recommended):
echo =====================================
echo 1. Install Python 3.10+ from python.org
echo    Download: https://www.python.org/downloads/
echo    IMPORTANT: Check "Add Python to PATH" during install
echo 2. Restart your computer
echo 3. Run this batch file again
echo.
echo QUICK FIX - Option B (Windows Store):
echo ======================================
echo 1. Open Windows Store
echo 2. Search for "Python 3.10" or "Python 3.11"
echo 3. Click Install
echo 4. Wait for installation
echo 5. Close and reopen Command Prompt/PowerShell
echo 6. Run this batch file again
echo.
pause
exit /b 1

:end
if errorlevel 1 (
    echo.
    echo Application exited with error.
    pause
)
