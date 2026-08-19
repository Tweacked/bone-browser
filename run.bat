@echo off
REM Bone Browser - Windows Launcher
REM Activates the venv and runs the browser

cd /d "%~dp0"

if not exist ".venv" (
    echo Creating virtual environment...
    python -m venv .venv
    call .venv\Scripts\activate.bat
    pip install PyQt6-WebEngine stem cryptography
) else (
    call .venv\Scripts\activate.bat
)

python browser.py %*
