@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo Create the Python 3.12 virtual environment and install requirements-dev.txt first.
  echo See README.md for setup instructions.
  pause
  exit /b 1
)
echo Starting SmartHireAI local preview. Keep this window open; Ctrl+C stops the server.
".venv\Scripts\python.exe" -u run_local.py %*
if errorlevel 1 pause
