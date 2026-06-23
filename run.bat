@echo off
rem One-step launcher for Windows: creates a local virtual environment, installs
rem dependencies on first run, then launches the app. Any arguments are passed
rem straight through (so "run.bat --input x.pdf" runs the CLI).
setlocal
cd /d "%~dp0"

if not exist ".venv" (
  echo Creating virtual environment...
  py -3 -m venv .venv 2>nul || python -m venv .venv
  if errorlevel 1 (
    echo ERROR: could not create a virtual environment. Install Python 3.10+ from python.org and retry.
    exit /b 1
  )
)

call ".venv\Scripts\activate.bat"
python -m pip install --quiet --upgrade pip
python -m pip install --quiet -r requirements.txt
if errorlevel 1 (
  echo ERROR: dependency install failed. Check your internet connection and Python setup.
  exit /b 1
)
python pdf2docx_app.py %*
