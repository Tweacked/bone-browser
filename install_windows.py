"""
Bone Browser - Windows Installer
Downloads Tor, creates Start Menu + Desktop shortcuts.

Run: python install_windows.py
"""

import os
import sys
import shutil
import subprocess
import zipfile
import tarfile
import urllib.request
from pathlib import Path

APP_NAME = "Bone Browser"
INSTALL_DIR = Path.home() / "AppData" / "Local" / "BoneBrowser"
TOR_DIR = INSTALL_DIR / "tor"
START_MENU = Path.home() / "AppData" / "Roaming" / "Microsoft" / "Windows" / "Start Menu" / "Programs" / APP_NAME
DESKTOP = Path.home() / "Desktop"
SOURCE_DIR = Path(__file__).parent

# Tor Expert Bundle URL (standalone tor.exe, no browser)
# Update this URL when new Tor versions release
TOR_VERSION = "0.4.8.12"
TOR_BUNDLE_URL = f"https://archive.torproject.org/tor-package/release/tor-expert-bundle-windows-x86_64-{TOR_VERSION}.tar.gz"
TOR_BUNDLE_FILE = INSTALL_DIR / "tor-bundle.tar.gz"


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


def download_tor():
    """Download and extract the Tor Expert Bundle."""
    print("  Downloading Tor Expert Bundle...")
    print(f"  URL: {TOR_BUNDLE_URL}")

    try:
        # Download with progress
        def progress(block, block_size, total):
            downloaded = block * block_size
            if total > 0:
                pct = min(100, downloaded * 100 // total)
                bar = "█" * (pct // 2) + "░" * (50 - pct // 2)
                print(f"\r  [{bar}] {pct}%  ", end="", flush=True)

        urllib.request.urlretrieve(TOR_BUNDLE_URL, str(TOR_BUNDLE_FILE), progress)
        print()  # Newline after progress bar
    except Exception as e:
        print(f"\n  Download failed: {e}")
        print("  You can manually download tor.exe from:")
        print("  https://www.torproject.org/download/tor/")
        print(f"  Place it in: {TOR_DIR}")
        return False

    # Extract
    print("  Extracting Tor...")
    TOR_DIR.mkdir(parents=True, exist_ok=True)

    try:
        with tarfile.open(str(TOR_BUNDLE_FILE), "r:gz") as tar:
            # Extract only tor.exe and required DLLs
            for member in tar.getmembers():
                if member.name.endswith((".exe", ".dll")):
                    member.name = os.path.basename(member.name)
                    tar.extract(member, str(TOR_DIR))
        print(f"  Extracted to: {TOR_DIR}")
    except Exception as e:
        print(f"  Extraction failed: {e}")
        # Try as zip as fallback
        try:
            with zipfile.ZipFile(str(TOR_BUNDLE_FILE)) as zf:
                for name in zf.namelist():
                    if name.endswith((".exe", ".dll")):
                        zf.extract(name, str(TOR_DIR))
        except Exception:
            pass

    # Clean up download
    if TOR_BUNDLE_FILE.exists():
        TOR_BUNDLE_FILE.unlink()

    # Verify tor.exe exists
    tor_exe = TOR_DIR / "tor.exe"
    if not tor_exe.exists():
        # Check subdirectories
        for f in TOR_DIR.rglob("tor.exe"):
            tor_exe = f
            break

    if tor_exe.exists():
        print(f"  Tor installed: {tor_exe}")
        return True
    else:
        print("  WARNING: tor.exe not found after extraction.")
        print(f"  Check: {TOR_DIR}")
        return False


def main():
    print("╔══════════════════════════════════════════╗")
    print("║    Bone Browser - Windows Installer      ║")
    print("╚══════════════════════════════════════════╝")
    print()

    # Check Python
    if sys.version_info < (3, 10):
        print("ERROR: Python 3.10+ is required.")
        print(f"  Your version: {sys.version}")
        sys.exit(1)

    # Create install directory
    print("[1/6] Creating install directory...")
    INSTALL_DIR.mkdir(parents=True, exist_ok=True)

    # Copy application files
    print("[2/6] Copying application files...")
    for f in ["browser.py", "run.bat", "icon.png"]:
        src = SOURCE_DIR / f
        if src.exists():
            shutil.copy2(src, INSTALL_DIR / f)
            print(f"  Copied: {f}")

    # Download Tor
    print("[3/6] Installing Tor...")
    tor_installed = download_tor()
    if not tor_installed:
        print()
        print("  Tor download failed, but Bone Browser will still work")
        print("  if you have Tor installed elsewhere on your system.")
        print()

    # Install Python dependencies
    print("[4/6] Installing Python dependencies...")
    venv_dir = INSTALL_DIR / ".venv"
    subprocess.run([sys.executable, "-m", "venv", str(venv_dir)], capture_output=True)
    pip = str(venv_dir / "Scripts" / "pip.exe")
    result = subprocess.run(
        [pip, "install", "PyQt6-WebEngine", "stem", "cryptography", "-q"],
        capture_output=True, text=True
    )
    if result.returncode == 0:
        print("  Dependencies installed.")
    else:
        print(f"  Warning: {result.stderr[:200]}")

    # Create Start Menu shortcut
    print("[5/6] Creating Start Menu entry...")
    START_MENU.mkdir(parents=True, exist_ok=True)
    shortcut_path = str(START_MENU / f"{APP_NAME}.lnk")
    target = str(INSTALL_DIR / "run.bat")
    icon = str(INSTALL_DIR / "icon.png")
    create_shortcut(target, shortcut_path, icon, "Secure Tor onion browser")

    # Create Desktop shortcut
    print("[6/6] Creating Desktop shortcut...")
    desktop_shortcut = str(DESKTOP / f"{APP_NAME}.lnk")
    create_shortcut(target, desktop_shortcut, icon, "Secure Tor onion browser")

    print()
    print("╔══════════════════════════════════════════╗")
    print("║         Installation Complete!           ║")
    print("╚══════════════════════════════════════════╝")
    print()
    print(f"  Start Menu: Search for '{APP_NAME}'")
    print(f"  Desktop:    {APP_NAME}.lnk")
    print(f"  Location:   {INSTALL_DIR}")
    if tor_installed:
        print(f"  Tor:        {TOR_DIR / 'tor.exe'}")
    print()
    print("  Double-click the shortcut to launch.")
    print()


if __name__ == "__main__":
    main()
