#!/bin/bash
# Bone Browser Launcher
# Activates the venv and runs the browser

DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$DIR"

if [ ! -d ".venv" ]; then
    echo "Creating virtual environment..."
    python3 -m venv .venv
    source .venv/bin/activate
    pip install PyQt6-WebEngine stem cryptography
else
    source .venv/bin/activate
fi

exec python3 browser.py "$@"