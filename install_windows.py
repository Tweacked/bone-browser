"""
Bone Browser - Windows Installer
Downloads Tor, creates Start Menu + Desktop shortcuts.

Run: python install_windows.py
"""

import os
import sys
import ssl
import shutil
import subprocess
import tarfile
import urllib.request
from pathlib import Path

APP_NAME = "Bone Browser"
INSTALL_DIR = Path.home() / "AppData" / "Local" / "BoneBrowser"
TOR_DIR = INSTALL_DIR / "tor"
START_MENU = Path.home() / "AppData" / "Roaming" / "Microsoft" / "Windows" / "Start Menu" / "Programs" / APP_NAME
DESKTOP = Path.home() / "Desktop"
SOURCE_DIR = Path(__file__).parent

# Tor Expert Bundle URL
TOR_VERSION = "0.4.8.12"
TOR_BUNDLE_URL = f"https://archive.torproject.org/tor-package/release/tor-expert-bundle-windows-x86_64-{TOR_VERSION}.tar.gz"
TOR_BUNDLE_FILE = INSTALL_DIR / "tor-bundle.tar.gz"


def create_shortcut(target, shortcut_path, icon_path, description, work_dir):
    """Create a Windows shortcut using PowerShell."""
    # Use forward slashes for PowerShell paths to avoid escape issues
    ps_target = target.replace("\\", "/")
    ps_shortcut = str(shortcut_path).replace("\\", "/")
    ps_icon = str(icon_path).replace("\\", "/")
    ps_work = str(work_dir).replace("\\", "/")
    ps_args = f'/c "{work_dir}\\launch.bat"'.replace("\\", "/")

    ps_script = (
        f"$ws = New-Object -ComObject WScript.Shell\n"
        f"$s = $ws.CreateShortcut('{ps_shortcut}')\n"
        f"$s.TargetPath = '{ps_target}'\n"
        f"$s.Arguments = '{ps_args}'\n"
        f"$s.WorkingDirectory = '{ps_work}'\n"
        f"$s.IconLocation = '{ps_icon},0'\n"
        f"$s.Description = '{description}'\n"
        f"$s.Save()"
    )
    result = subprocess.run(
        ["powershell", "-NoProfile", "-Command", ps_script],
        capture_output=True, text=True
    )
    if result.returncode != 0:
        print(f"  WARNING: Shortcut creation failed: {result.stderr[:200]}")
    return result.returncode == 0


def download_tor():
    """Download and extract the Tor Expert Bundle."""
    print("  Downloading Tor Expert Bundle...")
    print(f"  URL: {TOR_BUNDLE_URL}")

    def progress(block, block_size, total):
        downloaded = block * block_size
        if total > 0:
            pct = min(100, downloaded * 100 // total)
            bar = chr(9608) * (pct // 2) + chr(9617) * (50 - pct // 2)
            print(f"\r  [{bar}] {pct}%  ", end="", flush=True)

    downloaded_ok = False

    # Try normal download
    try:
        urllib.request.urlretrieve(TOR_BUNDLE_URL, str(TOR_BUNDLE_FILE), progress)
        print()
        downloaded_ok = True
    except Exception as e:
        print(f"\n  Download failed: {e}")

    # Retry with unverified SSL if first attempt failed
    if not downloaded_ok:
        try:
            print("  Retrying without SSL verification...")
            ctx = ssl._create_unverified_context()
            https_handler = urllib.request.HTTPSHandler(context=ctx)
            opener = urllib.request.build_opener(https_handler)
            urllib.request.install_opener(opener)
            urllib.request.urlretrieve(TOR_BUNDLE_URL, str(TOR_BUNDLE_FILE), progress)
            print()
            downloaded_ok = True
        except Exception as e2:
            print(f"  Retry failed: {e2}")

    if not downloaded_ok:
        print()
        print("  Manual install:")
        print(f"  1. Download tor.exe from https://www.torproject.org/download/tor/")
        print(f"  2. Place it in: {TOR_DIR}")
        print()
        return False

    print("  Extracting Tor...")
    TOR_DIR.mkdir(parents=True, exist_ok=True)

    try:
        with tarfile.open(str(TOR_BUNDLE_FILE), "r:gz") as tar:
            for member in tar.getmembers():
                if member.name.endswith((".exe", ".dll")):
                    member.name = os.path.basename(member.name)
                    tar.extract(member, str(TOR_DIR))
        print(f"  Extracted to: {TOR_DIR}")
    except Exception as e:
        print(f"  Extraction failed: {e}")
        return False
    finally:
        if TOR_BUNDLE_FILE.exists():
            TOR_BUNDLE_FILE.unlink()

    tor_exe = TOR_DIR / "tor.exe"
    if not tor_exe.exists():
        for f in TOR_DIR.rglob("tor.exe"):
            tor_exe = f
            break

    if tor_exe.exists():
        print(f"  Tor installed: {tor_exe}")
        return True
    else:
        print(f"  WARNING: tor.exe not found. Check: {TOR_DIR}")
        return False


def main():
    print("========================================")
    print("    Bone Browser - Windows Installer")
    print("========================================")
    print()

    if sys.version_info < (3, 10):
        print(f"ERROR: Python 3.10+ required. You have {sys.version}.")
        sys.exit(1)

    # [1/7] Create install directory
    print("[1/7] Creating install directory...")
    INSTALL_DIR.mkdir(parents=True, exist_ok=True)

    # [2/7] Copy application files
    print("[2/7] Copying application files...")
    for f in ["browser.py", "icon.ico", "icon.png"]:
        src = SOURCE_DIR / f
        if src.exists():
            shutil.copy2(src, INSTALL_DIR / f)
            print(f"  Copied: {f}")

    # [3/7] Create launcher bat
    print("[3/7] Creating launcher...")
    launch_bat = INSTALL_DIR / "launch.bat"
    bat_content = (
        "@echo off\r\n"
        "cd /d \"%~dp0\"\r\n"
        "if not exist \".venv\" (\r\n"
        "    echo Setting up Bone Browser...\r\n"
        "    python -m venv .venv\r\n"
        "    call .venv\\Scripts\\activate.bat\r\n"
        "    pip install PyQt6-WebEngine stem cryptography -q\r\n"
        ") else (\r\n"
        "    call .venv\\Scripts\\activate.bat\r\n"
        ")\r\n"
        "set \"PATH=%~dp0.venv\\Lib\\site-packages\\PyQt6\\Qt6\\bin;%~dp0tor;%PATH%\"\r\n"
        "start \"\" python browser.py\r\n"
    )
    launch_bat.write_text(bat_content)
    print(f"  Created: {launch_bat}")

    # [4/7] Download Tor
    print("[4/7] Installing Tor...")
    tor_installed = download_tor()
    if not tor_installed:
        print("  Continuing without bundled Tor...")

    # [5/7] Install Python dependencies
    print("[5/7] Installing Python dependencies...")
    venv_dir = INSTALL_DIR / ".venv"
    subprocess.run([sys.executable, "-m", "venv", str(venv_dir)], capture_output=True)
    pip = str(venv_dir / "Scripts" / "pip.exe")
    subprocess.run(
        [pip, "install", "PyQt6-WebEngine", "stem", "cryptography", "-q"],
        capture_output=True
    )
    print("  Dependencies installed.")

    # [6/7] Create Start Menu shortcut
    print("[6/7] Creating Start Menu entry...")
    START_MENU.mkdir(parents=True, exist_ok=True)
    icon_ico = str(INSTALL_DIR / "icon.ico")
    if not Path(icon_ico).exists():
        icon_ico = str(INSTALL_DIR / "icon.png")

    shortcut_path = START_MENU / f"{APP_NAME}.lnk"
    ok = create_shortcut(
        target="cmd.exe",
        shortcut_path=shortcut_path,
        icon_path=icon_ico,
        description="Secure Tor onion browser",
        work_dir=str(INSTALL_DIR)
    )
    if ok:
        print(f"  Created: {shortcut_path}")
    else:
        print("  Shortcut creation failed, but app can still run from launch.bat")

    # [7/7] Create Desktop shortcut
    print("[7/7] Creating Desktop shortcut...")
    desktop_shortcut = DESKTOP / f"{APP_NAME}.lnk"
    ok = create_shortcut(
        target="cmd.exe",
        shortcut_path=desktop_shortcut,
        icon_path=icon_ico,
        description="Secure Tor onion browser",
        work_dir=str(INSTALL_DIR)
    )
    if ok:
        print(f"  Created: {desktop_shortcut}")

    print()
    print("========================================")
    print("      Installation Complete!")
    print("========================================")
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
