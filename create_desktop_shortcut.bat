@echo off
REM Create Desktop Shortcut for PCB Printer GUI
REM Run this once to create a shortcut on your desktop

echo Creating desktop shortcut for PCB Printer GUI...
echo.

REM Get the app directory
set APP_DIR=%~dp0app
set LAUNCHER=%APP_DIR%\start_gui.bat

REM Get desktop path
for /f "tokens=3" %%A in ('reg query "HKEY_CURRENT_USER\Software\Microsoft\Windows\CurrentVersion\Explorer\Shell Folders" /v Desktop ^| findstr Desktop') do set DESKTOP=%%A

REM Create the shortcut using PowerShell
powershell -Command "^
  $shell = New-Object -ComObject WScript.Shell; ^
  $shortcut = $shell.CreateShortcut('%DESKTOP%\PCB Printer GUI.lnk'); ^
  $shortcut.TargetPath = '%LAUNCHER%'; ^
  $shortcut.WorkingDirectory = '%APP_DIR%'; ^
  $shortcut.Description = 'PCB Printer Motion Control with Camera Feedback'; ^
  $shortcut.Save(); ^
  Write-Host 'Shortcut created successfully!'
"

if errorlevel 1 (
    echo.
    echo Failed to create shortcut using PowerShell.
    echo.
    echo MANUAL METHOD:
    echo 1. Right-click on Desktop
    echo 2. Select "New" ^> "Shortcut"
    echo 3. Paste this path: %LAUNCHER%
    echo 4. Click Next
    echo 5. Name it: "PCB Printer GUI"
    echo 6. Click Finish
    echo.
) else (
    echo.
    echo ✓ Shortcut created on your desktop!
    echo ✓ Look for "PCB Printer GUI.lnk" on your desktop
    echo ✓ You can now launch the GUI by double-clicking the shortcut
    echo.
)

pause
