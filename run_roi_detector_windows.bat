@echo off
set SCRIPT_DIR=%~dp0

if exist "%SCRIPT_DIR%\.venv\Scripts\python.exe" (
  "%SCRIPT_DIR%\.venv\Scripts\python.exe" "%SCRIPT_DIR%run_roi_detector_gui.py"
) else (
  py "%SCRIPT_DIR%run_roi_detector_gui.py"
)

pause
