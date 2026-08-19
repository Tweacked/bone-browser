"""
Bone Browser - Windows Installer
Creates Start Menu shortcut and desktop shortcut.

Run: python install_windows.py
"""

import os
import sys
import shutil
import subprocess
from pathlib import Path

APP_NAME = "Bone Browser"
INSTALL_DIR = Path.home() / "AppData" / "Local" / "BoneBrowser"
START_MENU = Path.home() / "AppData" / "Roaming" / "Microsoft" / "Windows" / "Start Menu" / "Programs" / APP_NAME
DESKTOP = Path.home() / "Desktop"
SOURCE_DIR = Path(__file__).parent

def create_shortcut(target, shortcut_path, icon_path, description):
    """Create a Windows shortcut using PowerShell."""
    ps_script = f'''
$ws = New-Object -ComObject WScript.Shell
$shortcut = $ws.CreateShortcut("{shortcut_path}")
$shortcut.TargetPath = "{target}"
$shortcut.WorkingDirectory = "{INSTALL_DIR}"
$shortcut.IconLocation = "{icon_path}"
$shortcut.Description = "{description}"
$shortcut.Save()
'''
    subprocess.run(["powershell", "-Command", ps_script], capture_output=True)

def main():
    print("╔══════════════════════════════════════╗")
    print("║    Bone Browser - Windows Installer  ║")
    print("╚══════════════════════════════════════╝")
    print()

    # Check Python
    if sys.version_info < (3, 10):
        print("ERROR: Python 3.10+ is required.")
        sys.exit(1)

    # Create install directory
    print("[1/5] Creating install directory...")
    INSTALL_DIR.mkdir(parents=True, exist_ok=True)

    # Copy files
    print("[2/5] Copying application files...")
    for f in ["browser.py", "run.bat", "icon.png"]:
        src = SOURCE_DIR / f
        if src.exists():
            shutil.copy2(src, INSTALL_DIR / f)
            print(f"  Copied: {f}")

    # Create Start Menu folder
    print("[3/5] Creating Start Menu entry...")
    START_MENU.mkdir(parents=True, exist_ok=True)

    # Create Start Menu shortcut
    shortcut_path = str(START_MENU / f"{APP_NAME}.lnk")
    target = str(INSTALL_DIR / "run.bat")
    icon = str(INSTALL_DIR / "icon.png")
    create_shortcut(target, shortcut_path, icon, "Secure Tor onion browser")

    # Create Desktop shortcut
    print("[4/5] Creating Desktop shortcut...")
    desktop_shortcut = str(DESKTOP / f"{APP_NAME}.lnk")
    create_shortcut(target, desktop_shortcut, icon, "Secure Tor onion browser")

    # Install dependencies
    print("[5/5] Installing dependencies...")
    subprocess.run([sys.executable, "-m", "venv", str(INSTALL_DIR / ".venv")])
    pip = str(INSTALL_DIR / ".venv" / "Scripts" / "pip.exe")
    subprocess.run([pip, "install", "PyQt6-WebEngine", "stem", "cryptography", "-q"])

    print()
    print("╔══════════════════════════════════════╗")
    print("║    Installation Complete!            ║")
    print("╚══════════════════════════════════════╝")
    print()
    print(f"  Start Menu: {START_MENU}")
    print(f"  Desktop:    {DESKTOP / APP_NAME}.lnk")
    print(f"  Location:   {INSTALL_DIR}")
    print()
    print("  Double-click the shortcut on your Desktop or")
    print("  search for 'Bone Browser' in the Start Menu.")
    print()

if __name__ == "__main__":
    main()
