@echo off
REM PCB Printer GUI Launcher for Windows
REM Double-click this file to start the application

echo ============================================================
echo PCB Printer Control GUI
echo ============================================================
echo.

REM Get the directory where this batch file is located
cd /d "%~dp0"

REM Try to find Python
for /f "delims=" %%P in ('where python3 2^>nul ^| findstr /i python') do set PYTHON_EXE=%%P
if not defined PYTHON_EXE for /f "delims=" %%P in ('where python 2^>nul ^| findstr /i python') do set PYTHON_EXE=%%P

REM If still not found, try explicit paths
if not defined PYTHON_EXE (
    if exist "C:\Users\%USERNAME%\AppData\Local\Microsoft\WindowsApps\python3.exe" (
        set PYTHON_EXE=C:\Users\%USERNAME%\AppData\Local\Microsoft\WindowsApps\python3.exe
    ) else if exist "C:\Users\%USERNAME%\AppData\Local\Microsoft\WindowsApps\python.exe" (
        set PYTHON_EXE=C:\Users\%USERNAME%\AppData\Local\Microsoft\WindowsApps\python.exe
    )
)

if not defined PYTHON_EXE (
    echo.
    echo ERROR: Python not found on your system
    echo.
    echo To fix this:
    echo   1. Visit https://www.python.org/downloads/
    echo   2. Download Python 3.10 or later
    echo   3. IMPORTANT: Check "Add Python to PATH" during install
    echo   4. Restart your computer
    echo   5. Run this batch file again
    echo.
    pause
    exit /b 1
)

echo Found Python: %PYTHON_EXE%
"%PYTHON_EXE%" --version
echo.

echo Launching GUI...
"%PYTHON_EXE%" run_gui.py

if errorlevel 1 (
    echo.
    echo GUI exited with error.
    pause
)

