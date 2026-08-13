' PCB Printer GUI Launcher - VBScript Version
' Double-click this file to launch the GUI

Set objShell = CreateObject("WScript.Shell")
Set objFSO = CreateObject("Scripting.FileSystemObject")

' Get the directory where this script is located
strScriptPath = objFSO.GetParentFolderName(WScript.ScriptFullName)
objShell.CurrentDirectory = strScriptPath

' Try to find Python
strPython = ""

' Method 1: Try python3 in PATH
On Error Resume Next
Set objExec = objShell.Exec("where python3")
strPython = objExec.StdOut.ReadLine()
On Error Goto 0

' Method 2: Try python in PATH
If strPython = "" Then
    On Error Resume Next
    Set objExec = objShell.Exec("where python")
    strPython = objExec.StdOut.ReadLine()
    On Error Goto 0
End If

' Method 3: Try explicit paths
If strPython = "" Then
    If objFSO.FileExists("C:\Users\" & objShell.Environment("PROCESS")("USERNAME") & "\AppData\Local\Microsoft\WindowsApps\python3.exe") Then
        strPython = "C:\Users\" & objShell.Environment("PROCESS")("USERNAME") & "\AppData\Local\Microsoft\WindowsApps\python3.exe"
    End If
End If

If strPython = "" Then
    If objFSO.FileExists("C:\Users\" & objShell.Environment("PROCESS")("USERNAME") & "\AppData\Local\Microsoft\WindowsApps\python.exe") Then
        strPython = "C:\Users\" & objShell.Environment("PROCESS")("USERNAME") & "\AppData\Local\Microsoft\WindowsApps\python.exe"
    End If
End If

If strPython = "" Then
    MsgBox "Python not found!" & vbCrLf & vbCrLf & _
           "To fix this:" & vbCrLf & _
           "1. Install Python 3.10+ from https://www.python.org/downloads/" & vbCrLf & _
           "2. Check 'Add Python to PATH' during install" & vbCrLf & _
           "3. Restart your computer" & vbCrLf & _
           "4. Run this launcher again", _
           vbCritical, "Python Not Found"
    WScript.Quit 1
End If

' Launch the GUI
On Error Resume Next
objShell.Exec strPython & " run_gui.py"
On Error Goto 0

If Err.Number <> 0 Then
    MsgBox "Error launching GUI: " & Err.Description, vbCritical, "Error"
    WScript.Quit 1
End If
