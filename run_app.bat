@echo off
REM Batch file to run Profile Builder with proper environment
cd /d "%~dp0"

REM Try to run with virtual environment first
if exist ".venv\Scripts\python.exe" (
    .venv\Scripts\python.exe app.py
) else (
    REM Fall back to system Python
    python app.py
)

pause
