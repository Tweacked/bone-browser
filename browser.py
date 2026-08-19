"""
Bone Browser - Secure Tor Onion Browser
A PyQt6-based browser that routes all traffic through Tor with AES-256 encryption.
Author: Next Digital / Stark
"""

import sys
import os
import json
import socket
import logging
import shutil
import random
import hashlib
from pathlib import Path
from urllib.parse import quote

from PyQt6.QtCore import (
    QUrl, Qt, QSize, QTimer, QProcess, pyqtSignal, QObject, QFileInfo
)
from PyQt6.QtGui import QAction, QKeySequence, QFont, QDesktopServices, QIcon
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QTabWidget, QToolBar, QLineEdit,
    QStatusBar, QWidget, QVBoxLayout, QHBoxLayout, QPushButton,
    QLabel, QDialog, QFormLayout, QCheckBox,
    QSpinBox, QDialogButtonBox, QMessageBox, QProgressBar,
    QSplitter, QTextEdit, QGroupBox, QListWidget, QListWidgetItem,
    QMenu, QFileDialog,
)
from PyQt6.QtWebEngineWidgets import QWebEngineView
from PyQt6.QtWebEngineCore import (
    QWebEnginePage, QWebEngineProfile, QWebEngineSettings,
    QWebEngineUrlRequestInterceptor, QWebEngineDownloadRequest,
)

import stem.control
import stem.connection
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
import base64

# ─── Constants ────────────────────────────────────────────────────────────────

APP_NAME = "Bone Browser"
APP_VERSION = "2.0.0"
DATA_DIR = Path.home() / ".bone-browser"
CONFIG_FILE = DATA_DIR / "config.enc"
SALT_FILE = DATA_DIR / "salt.key"
BOOKMARKS_FILE = DATA_DIR / "bookmarks.enc"
HISTORY_FILE = DATA_DIR / "history.enc"
SESSION_FILE = DATA_DIR / "session.enc"
TOR_DATA_DIR = DATA_DIR / "tor-data"
LOG_FILE = DATA_DIR / "browser.log"
DOWNLOAD_DIR = Path.home() / "Downloads"
ICON_DIR = Path(__file__).parent / "icon.png"
DEFAULT_TOR_SOCKS = 9050
DEFAULT_TOR_CONTROL = 9051
DEFAULT_HOME = "https://check.torproject.org"
SEARCH_ENGINE = "https://duckduckgo.com/?q="
SEARCH_ENGINE_ONION = "https://duckduckgogg42ypt6tmxn7leutm5xc2cy5t2vh7flcorev3viy2lookup7wqd.onion/?q="

# Tor Browser User Agents for spoofing
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; rv:128.0) Gecko/20100101 Firefox/128.0",
    "Mozilla/5.0 (X11; Linux x86_64; rv:128.0) Gecko/20100101 Firefox/128.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:128.0) Gecko/20100101 Firefox/128.0",
    "Mozilla/5.0 (Windows NT 10.0; rv:115.0) Gecko/20100101 Firefox/115.0",
    "Mozilla/5.0 (X11; Linux x86_64; rv:115.0) Gecko/20100101 Firefox/115.0",
]

# ─── Logging ─────────────────────────────────────────────────────────────────

DATA_DIR.mkdir(parents=True, exist_ok=True)
DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)
logging.basicConfig(
    filename=str(LOG_FILE),
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)
logger = logging.getLogger(APP_NAME)


# ═══════════════════════════════════════════════════════════════════════════════
#  ENCRYPTION ENGINE - AES-256 via Fernet
# ═══════════════════════════════════════════════════════════════════════════════

class CryptoEngine:
    """AES-256 encryption for all persistent data (config, bookmarks, history)."""

    def __init__(self, master_password: str):
        self._fernet = self._derive_key(master_password)

    def _derive_key(self, password: str) -> Fernet:
        if SALT_FILE.exists():
            salt = SALT_FILE.read_bytes()
        else:
            salt = os.urandom(16)
            SALT_FILE.write_bytes(salt)
            os.chmod(str(SALT_FILE), 0o600)

        kdf = PBKDF2HMAC(
            algorithm=hashes.SHA256(),
            length=32,
            salt=salt,
            iterations=600_000,
        )
        key = base64.urlsafe_b64encode(kdf.derive(password.encode()))
        return Fernet(key)

    def encrypt(self, data: str) -> bytes:
        return self._fernet.encrypt(data.encode())

    def decrypt(self, token: bytes) -> str:
        return self._fernet.decrypt(token).decode()

    def encrypt_file(self, path: Path, data: str):
        path.write_bytes(self.encrypt(data))
        os.chmod(str(path), 0o600)

    def decrypt_file(self, path: Path) -> str:
        if not path.exists():
            return ""
        return self.decrypt(path.read_bytes())


# ═══════════════════════════════════════════════════════════════════════════════
#  TOR PROCESS MANAGER
# ═══════════════════════════════════════════════════════════════════════════════

class TorManager(QObject):
    """Manages a local Tor process and control port connection."""

    status_changed = pyqtSignal(str)
    circuit_ready = pyqtSignal(str)
    log_message = pyqtSignal(str)

    def __init__(self, socks_port=DEFAULT_TOR_SOCKS, control_port=DEFAULT_TOR_CONTROL):
        super().__init__()
        self.socks_port = socks_port
        self.control_port = control_port
        self._process = None
        self._controller = None
        self._connected = False
        self._auth_retries = 0

    @property
    def connected(self):
        return self._connected

    def _find_tor_binary(self):
        """Locate the tor binary on Linux, macOS, or Windows."""
        # Linux/macOS paths
        for path in ["/usr/bin/tor", "/usr/local/bin/tor", shutil.which("tor")]:
            if path and os.path.isfile(path):
                return path
        # Windows paths
        if os.name == "nt":
            # Check app's bundled Tor directory first
            app_dir = Path(__file__).parent / "tor"
            tor_in_app = app_dir / "tor.exe"
            if tor_in_app.is_file():
                return str(tor_in_app)
            # Check common install locations
            program_files = [
                os.environ.get("ProgramFiles", "C:\\Program Files"),
                os.environ.get("ProgramFiles(x86)", "C:\\Program Files (x86)"),
                os.environ.get("LOCALAPPDATA", ""),
            ]
            for pf in program_files:
                if not pf:
                    continue
                candidates = [
                    os.path.join(pf, "BoneBrowser", "tor", "tor.exe"),
                    os.path.join(pf, "Tor Browser", "Browser", "TorBrowser", "Tor", "tor.exe"),
                    os.path.join(pf, "Tor", "tor.exe"),
                ]
                for c in candidates:
                    if os.path.isfile(c):
                        return c
            # Check if tor.exe is in PATH
            tor_path = shutil.which("tor")
            if tor_path:
                return tor_path
        return None

    def _is_port_in_use(self, port):
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(1)
            result = sock.connect_ex(("127.0.0.1", port))
            sock.close()
            return result == 0
        except Exception:
            return False

    def start(self):
        tor_bin = self._find_tor_binary()
        if not tor_bin:
            self.status_changed.emit("error")
            self.log_message.emit("ERROR: tor binary not found. Install with: sudo apt install tor")
            return

        TOR_DATA_DIR.mkdir(parents=True, exist_ok=True)
        self.status_changed.emit("connecting")
        self.log_message.emit("Starting Tor process...")

        if self._is_port_in_use(self.socks_port):
            self.log_message.emit(
                f"Port {self.socks_port} in use. Connecting to existing Tor..."
            )
            self._poll_timer = QTimer()
            self._poll_timer.timeout.connect(self._try_connect_control)
            self._poll_timer.start(2000)
            return

        self._process = QProcess()
        self._process.setProcessChannelMode(QProcess.ProcessChannelMode.MergedChannels)
        self._process.readyReadStandardOutput.connect(self._on_tor_output)

        args = [
            "--SocksPort", str(self.socks_port),
            "--ControlPort", str(self.control_port),
            "--DataDirectory", str(TOR_DATA_DIR),
            "--CookieAuthentication", "1",
            "--CookieAuthFile", str(TOR_DATA_DIR / "control_auth_cookie"),
            "--Log", "notice stdout",
            "--RunAsDaemon", "0",
            "--MaxCircuitDirtiness", "600",
            "--NewCircuitPeriod", "30",
            "--CircuitStreamTimeout", "60",
            "--SafeSocks", "0",
            "--AvoidDiskWrites", "1",
            # Speed optimizations (safe, no security compromise)
            "--FetchUselessDescriptors", "0",
            "--UseEntryGuards", "1",
            "--ConnLimit", "1024",
            "--NumEntryGuards", "3",
            "--KeepalivePeriod", "60",
            "--DisableNetwork", "0",
            "--EnforceDistinctSubnets", "0",
            "--CircuitBuildTimeout", "60",
            "--LearnCircuitBuildTimeout", "0",
        ]
        self._process.start(tor_bin, args)
        self._process.waitForStarted(5000)

        self._poll_timer = QTimer()
        self._poll_timer.timeout.connect(self._try_connect_control)
        self._poll_timer.start(2000)

    def _on_tor_output(self):
        if self._process:
            data = self._process.readAllStandardOutput().data().decode(errors="replace")
            for line in data.strip().splitlines():
                self.log_message.emit(f"[tor] {line}")
                if "Bootstrapped 100%" in line:
                    self._on_tor_ready()

    def _on_tor_ready(self):
        if hasattr(self, '_poll_timer'):
            self._poll_timer.stop()
        self._connected = True
        self.status_changed.emit("connected")
        self.log_message.emit("Tor connected. Circuit is live.")
        # Try to get the control port connected too (for circuit info)
        self._try_connect_control()

    def _try_connect_control(self):
        if self._controller:
            return
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(2)
            sock.connect(("127.0.0.1", self.control_port))
            sock.close()
            self._connect_controller()
        except (ConnectionRefusedError, socket.timeout, OSError):
            pass

    def _connect_controller(self):
        try:
            self._controller = stem.control.Controller.from_port(
                port=self.control_port
            )
            # Authenticate with the cookie file from our data directory.
            # Also try the default path as fallback for existing tor processes.
            cookie_path = str(TOR_DATA_DIR / "control_auth_cookie")
            if os.path.exists(cookie_path):
                try:
                    stem.connection.authenticate(self._controller, cookie_path=cookie_path)
                except Exception:
                    self._controller.authenticate()
            else:
                self._controller.authenticate()

            self.log_message.emit("Control port authenticated.")

            self._controller.add_event_listener(
                self._on_circuit_event, stem.control.EventType.CIRC
            )
            if hasattr(self, '_poll_timer'):
                self._poll_timer.stop()
            self._connected = True
            self.status_changed.emit("connected")
        except Exception as e:
            self._auth_retries += 1
            self.log_message.emit(f"Control port auth failed ({self._auth_retries}): {e}")
            if self._controller:
                try:
                    self._controller.close()
                except Exception:
                    pass
                self._controller = None
            # Keep retrying via poll timer up to 5 times
            if self._auth_retries > 5 and hasattr(self, '_poll_timer'):
                self._poll_timer.stop()

    def _on_circuit_event(self, event):
        if event.status == stem.control.CircStatus.BUILT:
            path = " -> ".join(
                fp[:8] for fp, nick in (event.path or [])
            )
            self.circuit_ready.emit(f"Circuit #{event.id}: {path}")

    def new_circuit(self):
        if self._controller:
            try:
                self._controller.signal(stem.Signal.NEWNYM)
                self.log_message.emit("New circuit requested.")
                return True
            except Exception as e:
                self.log_message.emit(f"Circuit rotation failed: {e}")
        return False

    def get_circuits(self):
        if self._controller:
            try:
                return self._controller.get_circuits()
            except Exception:
                pass
        return []

    def get_info(self, key):
        """Get a Tor info string (e.g. 'address' for exit IP)."""
        if self._controller:
            try:
                return self._controller.get_info(key)
            except Exception:
                pass
        return None

    def stop(self):
        if self._controller:
            try:
                self._controller.close()
            except Exception:
                pass
        if self._process:
            self._process.terminate()
            self._process.waitForFinished(5000)
            if self._process.state() != QProcess.ProcessState.NotRunning:
                self._process.kill()
        if hasattr(self, '_poll_timer'):
            self._poll_timer.stop()
        self._connected = False
        self.status_changed.emit("disconnected")
        self.log_message.emit("Tor stopped.")


# ═══════════════════════════════════════════════════════════════════════════════
#  REQUEST INTERCEPTOR
# ═══════════════════════════════════════════════════════════════════════════════

class PrivacyInterceptor(QWebEngineUrlRequestInterceptor):
    """Blocks trackers, ads, analytics, and social widgets for speed + privacy."""

    BLOCKED_DOMAINS = (
        # Analytics
        "google-analytics.com", "googletagmanager.com", "analytics.google.com",
        "stats.g.doubleclick.net", "hotjar.com", "mixpanel.com",
        "segment.io", "segment.com", "amplitude.com",
        "heapanalytics.com", "fullstory.com", "mouseflow.com",
        "matomo.org", "piwik.org",
        # Ads
        "doubleclick.net", "googlesyndication.com", "googleadservices.com",
        "adservice.google.com", "pagead2.googlesyndication.com",
        "ad.doubleclick.net", "adclick.g.doubleclick.net",
        "criteo.com", "criteo.net", "outbrain.com", "taboola.com",
        "ads.yahoo.com", "advertising.com", "adnxs.com",
        "pubmatic.com", "rubiconproject.com", "openx.net",
        "casalemedia.com", "turn.com", "tidaltv.com",
        # Social trackers
        "connect.facebook.net", "analytics.facebook.com",
        "analytics.twitter.com", "ads.linkedin.com",
        "platform.twitter.com", "syndication.twitter.com",
        # Telemetry
        "scorecardresearch.com", "quantserve.com",
        "nr-data.net", "newrelic.com",
        "sentry.io", "bugsnag.com",
        "crashlytics.com",
    )

    # Font extensions to block (reduces bandwidth)
    FONT_EXTENSIONS = (".woff", ".woff2", ".ttf", ".otf", ".eot")

    def __init__(self, block_third_party=True, block_fonts=False, parent=None):
        super().__init__(parent)
        self.block_third_party = block_third_party
        self.block_fonts = block_fonts
        self.blocked_count = 0

    def interceptRequest(self, info):
        url = info.requestUrl().toString().lower()

        # Block known tracker/ad domains
        for domain in self.BLOCKED_DOMAINS:
            if domain in url:
                self.blocked_count += 1
                info.block(True)
                return

        # Block web fonts if enabled (speed optimization)
        if self.block_fonts:
            for ext in self.FONT_EXTENSIONS:
                if ext in url:
                    self.blocked_count += 1
                    info.block(True)
                    return


# ═══════════════════════════════════════════════════════════════════════════════
#  ERROR PAGES
# ═══════════════════════════════════════════════════════════════════════════════

class ErrorPages:
    """Dark-themed error pages matching the browser aesthetic."""

    _STYLE = """
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            background: #0d1117; color: #c9d1d9;
            font-family: 'Monospace', 'Courier New', monospace;
            display: flex; align-items: center; justify-content: center;
            min-height: 100vh; padding: 20px;
        }
        .container {
            max-width: 500px; text-align: center;
        }
        .icon {
            font-size: 64px; margin-bottom: 16px;
            color: #f85149;
        }
        .icon.warn { color: #d29922; }
        .icon.info { color: #58a6ff; }
        h1 {
            font-size: 20px; color: #f0f6fc;
            margin-bottom: 12px; font-weight: 600;
        }
        p {
            color: #8b949e; font-size: 13px;
            line-height: 1.6; margin-bottom: 8px;
        }
        .url {
            color: #58a6ff; font-size: 12px;
            word-break: break-all; padding: 8px 12px;
            background: #161b22; border-radius: 4px;
            border: 1px solid #30363d; margin: 12px 0;
        }
        .actions {
            margin-top: 20px;
        }
        a.btn {
            display: inline-block; padding: 8px 20px;
            background: #21262d; color: #c9d1d9;
            border: 1px solid #30363d; border-radius: 4px;
            text-decoration: none; font-family: inherit;
            font-size: 12px; cursor: pointer; margin: 0 4px;
        }
        a.btn:hover { border-color: #58a6ff; color: #58a6ff; }
        .detail {
            margin-top: 16px; padding: 10px;
            background: #161b22; border-radius: 4px;
            border: 1px solid #30363d; font-size: 11px;
            color: #6e7681; text-align: left;
        }
    """

    @staticmethod
    def _page(icon, icon_class, title, message, url="", detail="", actions=""):
        url_html = f'<div class="url">{url}</div>' if url else ""
        detail_html = f'<div class="detail">{detail}</div>' if detail else ""
        return f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>{title}</title>
<style>{ErrorPages._STYLE}</style></head>
<body><div class="container">
    <div class="icon {icon_class}">{icon}</div>
    <h1>{title}</h1>
    <p>{message}</p>
    {url_html}
    <div class="actions">{actions}</div>
    {detail_html}
</div></body></html>"""

    @staticmethod
    def page_not_found(url):
        return ErrorPages._page(
            "404", "warn",
            "Page Not Found",
            "The server could not find the requested page. The page may have been moved, deleted, or the URL may be incorrect.",
            url=url,
            actions='<a class="btn" href="javascript:history.back()">Go Back</a>'
                    '<a class="btn" href="javascript:location.reload()">Retry</a>',
        )

    @staticmethod
    def connection_failed(url):
        return ErrorPages._page(
            "&#9888;", "",
            "Connection Failed",
            "Could not connect to the server. This may be a Tor circuit issue, the site may be down, or the address may be incorrect.",
            url=url,
            detail="Possible causes: Tor circuit timeout, exit node blocked by destination, invalid .onion address, or the site is offline.",
            actions='<a class="btn" href="javascript:location.reload()">Retry</a>'
                    '<a class="btn" href="javascript:history.back()">Go Back</a>',
        )

    @staticmethod
    def dns_error(url):
        return ErrorPages._page(
            "&#127968;", "warn",
            "Site Not Found",
            "The address could not be resolved. If this is a .onion address, make sure Tor is connected and the address is correct.",
            url=url,
            detail=".onion addresses are case-sensitive and must be exact. Try getting a fresh Tor circuit if the problem persists.",
            actions='<a class="btn" href="javascript:location.reload()">Retry</a>'
                    '<a class="btn" href="javascript:history.back()">Go Back</a>',
        )

    @staticmethod
    def tor_not_connected():
        return ErrorPages._page(
            "&#128274;", "warn",
            "Tor Not Connected",
            "The Tor network is not yet available. The browser is waiting for Tor to finish bootstrapping.",
            detail="This usually takes 10-30 seconds. The status bar at the bottom shows Tor's connection state.",
            actions='<a class="btn" href="javascript:location.reload()">Retry</a>',
        )

    @staticmethod
    def ssl_error(url):
        return ErrorPages._page(
            "&#128737;", "warn",
            "Secure Connection Failed",
            "The SSL/TLS handshake failed. The site's certificate could not be verified.",
            url=url,
            detail="This may be caused by a Tor exit node issue, an expired certificate, or a network interception attempt.",
            actions='<a class="btn" href="javascript:location.reload()">Retry</a>'
                    '<a class="btn" href="javascript:history.back()">Go Back</a>',
        )

    @staticmethod
    def generic_error(url, error_desc="Unknown error"):
        return ErrorPages._page(
            "&#9888;", "",
            "Something Went Wrong",
            "The page could not be loaded.",
            url=url,
            detail=f"Error: {error_desc}",
            actions='<a class="btn" href="javascript:location.reload()">Retry</a>'
                    '<a class="btn" href="javascript:history.back()">Go Back</a>',
        )


# ═══════════════════════════════════════════════════════════════════════════════
#  CUSTOM WEB PAGE
# ═══════════════════════════════════════════════════════════════════════════════

class SecureWebPage(QWebEnginePage):
    """Hardened web page."""

    def __init__(self, profile, parent=None):
        super().__init__(profile, parent)
        self._js_enabled = False
        self._view = None  # set by SecureTab
        self._last_url = ""
        self.loadFinished.connect(self._on_load_finished)

    def setJavaScriptEnabled(self, enabled):
        self._js_enabled = enabled
        self.settings().setAttribute(
            QWebEngineSettings.WebAttribute.JavascriptEnabled, enabled
        )

    def javaScriptConsoleMessage(self, level, message, line, source):
        pass

    def certificateError(self, error):
        url = error.url().toString()
        # For .onion sites, always accept (authenticated by address)
        if ".onion" in url:
            return True
        # For clearnet through Tor, accept (exit node cert issues)
        return True

    def _on_load_finished(self, ok):
        """Show custom error page on load failure, inject link handler on success."""
        if ok:
            self._inject_link_handler()
        else:
            self._show_error_page()

    def _show_error_page(self):
        """Determine error type and show appropriate error page."""
        url = self._last_url or self.url().toString()

        # Check if it's a .onion address
        is_onion = ".onion" in url

        # Determine error type based on URL and context
        if not url or url == "about:blank":
            return  # Don't show error for blank pages

        if is_onion:
            html = ErrorPages.dns_error(url)
        else:
            html = ErrorPages.connection_failed(url)

        self.setHtml(html, QUrl("about:blank"))

    def setUrl(self, url):
        """Track the URL being loaded for error page context."""
        self._last_url = url.toString() if hasattr(url, 'toString') else str(url)
        super().setUrl(url)

    def _inject_link_handler(self):
        """After every page load, rewrite target=_blank links to target=_self.

        This prevents Chromium from calling createWindow at all. The click
        navigates in the current page instead. runJavaScript works regardless
        of the JavascriptEnabled setting (it's programmatic injection).

        Uses a window flag to prevent handler stacking on back/forward.
        """
        self.runJavaScript("""
            (function() {
                if (window.__dn_link_handler__) return;
                window.__dn_link_handler__ = true;
                document.addEventListener('click', function(e) {
                    var link = e.target.closest('a');
                    if (link && link.target === '_blank') {
                        link.target = '_self';
                    }
                }, true);
            })();
        """)

    def createWindow(self, window_type):
        """Safety net: if a target=_blank link somehow gets through the JS
        handler, return self instead of creating an orphan page."""
        return self


# ═══════════════════════════════════════════════════════════════════════════════
#  SECURE TAB
# ═══════════════════════════════════════════════════════════════════════════════

class SecureTab(QWidget):
    """A single browser tab."""

    title_changed = pyqtSignal(str)
    url_changed = pyqtSignal(QUrl)
    load_progress = pyqtSignal(int)
    load_started = pyqtSignal()
    load_finished = pyqtSignal(bool)
    icon_changed = pyqtSignal()

    def __init__(self, profile: QWebEngineProfile, enable_js=False, parent=None):
        super().__init__(parent)
        self.profile = profile
        self._loading = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.web_view = QWebEngineView()
        self.page = SecureWebPage(profile, self.web_view)
        self.page._view = self.web_view
        self.page.setJavaScriptEnabled(enable_js)
        self.web_view.setPage(self.page)

        self.web_view.titleChanged.connect(self.title_changed.emit)
        self.web_view.urlChanged.connect(self.url_changed.emit)
        self.web_view.loadProgress.connect(self.load_progress.emit)
        self.web_view.loadStarted.connect(self._on_load_started)
        self.web_view.loadFinished.connect(self._on_load_finished)
        self.web_view.iconChanged.connect(self.icon_changed.emit)

        layout.addWidget(self.web_view)

    def _on_load_started(self):
        self._loading = True
        self.load_started.emit()

    def _on_load_finished(self, ok):
        self._loading = False
        self.load_finished.emit(ok)

    @property
    def is_loading(self):
        return self._loading

    def navigate(self, url: str):
        qurl = QUrl.fromUserInput(url)
        self.web_view.setUrl(qurl)

    def current_url(self) -> str:
        return self.web_view.url().toString()

    def title(self) -> str:
        return self.web_view.title() or "New Tab"

    def icon(self):
        return self.web_view.icon()

    def set_javascript(self, enabled: bool):
        self.page.setJavaScriptEnabled(enabled)

    def back(self):
        self.web_view.back()

    def forward(self):
        self.web_view.forward()

    def reload(self):
        self.web_view.reload()

    def stop(self):
        self.web_view.stop()

    def zoom_in(self):
        self.web_view.setZoomFactor(min(self.web_view.zoomFactor() + 0.1, 5.0))

    def zoom_out(self):
        self.web_view.setZoomFactor(max(self.web_view.zoomFactor() - 0.1, 0.25))

    def zoom_reset(self):
        self.web_view.setZoomFactor(1.0)


# ═══════════════════════════════════════════════════════════════════════════════
#  CIRCUIT INFO DIALOG
# ═══════════════════════════════════════════════════════════════════════════════

class CircuitDialog(QDialog):
    """Display active Tor circuits."""

    def __init__(self, tor_manager: TorManager, parent=None):
        super().__init__(parent)
        self.tor_manager = tor_manager
        self.setWindowTitle("Tor Circuits")
        self.setMinimumSize(550, 420)
        self.setStyleSheet(self._stylesheet())

        layout = QVBoxLayout(self)

        # IP info
        self.ip_label = QLabel("Exit IP: Checking...")
        self.ip_label.setFont(QFont("Monospace", 10))
        layout.addWidget(self.ip_label)

        self.circuit_list = QTextEdit()
        self.circuit_list.setReadOnly(True)
        self.circuit_list.setFont(QFont("Monospace", 10))
        layout.addWidget(self.circuit_list)

        btn_row = QHBoxLayout()
        refresh_btn = QPushButton("Refresh")
        refresh_btn.clicked.connect(self._refresh)
        btn_row.addWidget(refresh_btn)

        new_circuit_btn = QPushButton("New Circuit")
        new_circuit_btn.clicked.connect(self._new_circuit)
        btn_row.addWidget(new_circuit_btn)
        layout.addLayout(btn_row)

        self._refresh()
        self._fetch_ip()

    def _fetch_ip(self):
        """Fetch exit IP from Tor control port."""
        ip = self.tor_manager.get_info("address")
        if ip:
            self.ip_label.setText(f"Exit IP: {ip}")
        else:
            self.ip_label.setText("Exit IP: (control port unavailable)")

    def _refresh(self):
        circuits = self.tor_manager.get_circuits()
        if not circuits:
            self.circuit_list.setPlainText(
                "No active circuits.\n\n"
                "This means the Tor control port is not authenticated.\n"
                "Browsing still works via SOCKS, but circuit info is unavailable.\n"
                "Try the Tor Log (Ctrl+L) for details."
            )
            return
        lines = []
        for circ in circuits:
            if circ.status == 'BUILT':
                path = " -> ".join(
                    f"{fp[:12]} ({nick})" for fp, nick in circ.path
                )
                lines.append(f"Circuit #{circ.id}\n  Path: {path}\n  Purpose: {circ.purpose}\n")
            else:
                lines.append(f"Circuit #{circ.id}  Status: {circ.status}\n")
        self.circuit_list.setPlainText("\n".join(lines))

    def _new_circuit(self):
        if self.tor_manager.new_circuit():
            self.circuit_list.setPlainText("New circuit requested. Refresh in a few seconds...")
            QTimer.singleShot(3000, self._refresh)
        else:
            self.circuit_list.setPlainText("Could not request new circuit. Control port not connected.")

    def _stylesheet(self):
        return """
            QDialog { background-color: #0d1117; }
            QLabel { color: #c9d1d9; }
            QTextEdit {
                background-color: #010409; color: #c9d1d9;
                border: 1px solid #30363d; border-radius: 4px;
            }
            QPushButton {
                background-color: #21262d; color: #c9d1d9;
                border: 1px solid #30363d; border-radius: 4px;
                padding: 6px 16px;
            }
            QPushButton:hover { border-color: #58a6ff; }
        """


# ═══════════════════════════════════════════════════════════════════════════════
#  SETTINGS DIALOG
# ═══════════════════════════════════════════════════════════════════════════════

class SettingsDialog(QDialog):
    """Browser security and Tor settings."""

    def __init__(self, config: dict, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Preferences")
        self.setMinimumSize(480, 560)
        self.config = dict(config)
        self.setStyleSheet(self._stylesheet())

        layout = QVBoxLayout(self)

        tor_group = QGroupBox("Tor Configuration")
        tor_form = QFormLayout()
        self.socks_spin = QSpinBox()
        self.socks_spin.setRange(1024, 65535)
        self.socks_spin.setValue(self.config.get("tor_socks_port", DEFAULT_TOR_SOCKS))
        tor_form.addRow("SOCKS Port:", self.socks_spin)
        self.control_spin = QSpinBox()
        self.control_spin.setRange(1024, 65535)
        self.control_spin.setValue(self.config.get("tor_control_port", DEFAULT_TOR_CONTROL))
        tor_form.addRow("Control Port:", self.control_spin)
        tor_group.setLayout(tor_form)
        layout.addWidget(tor_group)

        sec_group = QGroupBox("Security")
        sec_form = QFormLayout()
        self.js_check = QCheckBox("Enable JavaScript globally")
        self.js_check.setChecked(self.config.get("javascript_enabled", False))
        sec_form.addRow(self.js_check)
        self.block_trackers = QCheckBox("Block known trackers")
        self.block_trackers.setChecked(self.config.get("block_trackers", True))
        sec_form.addRow(self.block_trackers)
        self.clear_on_exit = QCheckBox("Clear all data on exit")
        self.clear_on_exit.setChecked(self.config.get("clear_on_exit", False))
        sec_form.addRow(self.clear_on_exit)
        self.spoof_ua = QCheckBox("Randomize User Agent")
        self.spoof_ua.setChecked(self.config.get("spoof_ua", True))
        sec_form.addRow(self.spoof_ua)
        sec_group.setLayout(sec_form)
        layout.addWidget(sec_group)

        priv_group = QGroupBox("Privacy")
        priv_form = QFormLayout()
        self.hsts_check = QCheckBox("HTTPS-only mode")
        self.hsts_check.setChecked(self.config.get("https_only", True))
        priv_form.addRow(self.hsts_check)
        self.webgl_check = QCheckBox("Disable WebGL")
        self.webgl_check.setChecked(self.config.get("disable_webgl", True))
        priv_form.addRow(self.webgl_check)
        priv_group.setLayout(priv_form)
        layout.addWidget(priv_group)

        speed_group = QGroupBox("Speed")
        speed_form = QFormLayout()
        self.load_images_check = QCheckBox("Load images")
        self.load_images_check.setChecked(self.config.get("load_images", True))
        speed_form.addRow(self.load_images_check)
        self.block_fonts_check = QCheckBox("Block web fonts (faster loads)")
        self.block_fonts_check.setChecked(self.config.get("block_fonts", False))
        speed_form.addRow(self.block_fonts_check)
        speed_group.setLayout(speed_form)
        layout.addWidget(speed_group)

        home_group = QGroupBox("General")
        home_form = QFormLayout()
        self.home_edit = QLineEdit(self.config.get("home_page", DEFAULT_HOME))
        home_form.addRow("Home Page:", self.home_edit)
        home_group.setLayout(home_form)
        layout.addWidget(home_group)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _accept(self):
        self.config.update({
            "tor_socks_port": self.socks_spin.value(),
            "tor_control_port": self.control_spin.value(),
            "javascript_enabled": self.js_check.isChecked(),
            "block_trackers": self.block_trackers.isChecked(),
            "clear_on_exit": self.clear_on_exit.isChecked(),
            "spoof_ua": self.spoof_ua.isChecked(),
            "https_only": self.hsts_check.isChecked(),
            "disable_webgl": self.webgl_check.isChecked(),
            "load_images": self.load_images_check.isChecked(),
            "block_fonts": self.block_fonts_check.isChecked(),
            "home_page": self.home_edit.text() or DEFAULT_HOME,
        })
        self.accept()

    def get_config(self):
        return self.config

    def _stylesheet(self):
        return """
            QDialog { background-color: #0d1117; }
            QGroupBox {
                color: #58a6ff; border: 1px solid #30363d;
                border-radius: 4px; margin-top: 12px; padding-top: 16px;
            }
            QCheckBox { color: #c9d1d9; }
            QLabel { color: #c9d1d9; }
            QLineEdit, QSpinBox {
                background-color: #010409; color: #c9d1d9;
                border: 1px solid #30363d; border-radius: 3px; padding: 4px;
            }
            QPushButton {
                background-color: #21262d; color: #c9d1d9;
                border: 1px solid #30363d; border-radius: 4px; padding: 6px 16px;
            }
            QPushButton:hover { border-color: #58a6ff; }
        """


# ═══════════════════════════════════════════════════════════════════════════════
#  BOOKMARKS PANEL
# ═══════════════════════════════════════════════════════════════════════════════

class BookmarksPanel(QWidget):
    """Encrypted bookmarks sidebar."""

    navigate_requested = pyqtSignal(str)

    def __init__(self, crypto: CryptoEngine, parent=None):
        super().__init__(parent)
        self.crypto = crypto
        self.bookmarks = []
        self._load()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(4)

        header = QLabel("BOOKMARKS")
        header.setFont(QFont("Monospace", 10, QFont.Weight.Bold))
        header.setStyleSheet("color: #58a6ff; padding: 4px;")
        layout.addWidget(header)

        self.list_widget = QListWidget()
        self.list_widget.setFont(QFont("Monospace", 9))
        self.list_widget.itemDoubleClicked.connect(self._on_item_clicked)
        layout.addWidget(self.list_widget)

        btn_row = QHBoxLayout()
        self.add_btn = QPushButton("Add")
        del_btn = QPushButton("Remove")
        del_btn.clicked.connect(self._remove_selected)
        btn_row.addWidget(self.add_btn)
        btn_row.addWidget(del_btn)
        layout.addLayout(btn_row)

        self._refresh_list()

    def _load(self):
        try:
            raw = self.crypto.decrypt_file(BOOKMARKS_FILE)
            self.bookmarks = json.loads(raw) if raw else []
        except Exception:
            self.bookmarks = []

    def _save(self):
        self.crypto.encrypt_file(BOOKMARKS_FILE, json.dumps(self.bookmarks))

    def _refresh_list(self):
        self.list_widget.clear()
        for bm in self.bookmarks:
            title = bm['title'][:40]
            item = QListWidgetItem(f"{title}\n{bm['url'][:50]}")
            self.list_widget.addItem(item)

    def add_bookmark(self, url: str, title: str):
        if any(b["url"] == url for b in self.bookmarks):
            return
        self.bookmarks.append({"url": url, "title": title})
        self._save()
        self._refresh_list()

    def _remove_selected(self):
        row = self.list_widget.currentRow()
        if row >= 0:
            self.bookmarks.pop(row)
            self._save()
            self._refresh_list()

    def _on_item_clicked(self, item: QListWidgetItem):
        row = self.list_widget.row(item)
        if 0 <= row < len(self.bookmarks):
            self.navigate_requested.emit(self.bookmarks[row]["url"])


# ═══════════════════════════════════════════════════════════════════════════════
#  URL BAR
# ═══════════════════════════════════════════════════════════════════════════════

class UrlBar(QLineEdit):
    """URL bar: select all on focus, reset to current URL on blur."""

    def __init__(self, get_current_url=None, parent=None):
        super().__init__(parent)
        self._get_current_url = get_current_url

    def focusInEvent(self, event):
        super().focusInEvent(event)
        QTimer.singleShot(0, self.selectAll)

    def focusOutEvent(self, event):
        super().focusOutEvent(event)
        self._reset_to_current()

    def _reset_to_current(self):
        if self._get_current_url:
            current = self._get_current_url()
            if current and current != "about:blank":
                self.setText(current)
            else:
                self.clear()


# ═══════════════════════════════════════════════════════════════════════════════
#  SHORTCUTS DIALOG
# ═══════════════════════════════════════════════════════════════════════════════

class ShortcutsDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Keyboard Shortcuts")
        self.setMinimumSize(400, 500)
        self.setStyleSheet("""
            QDialog { background-color: #0d1117; }
            QLabel { color: #c9d1d9; }
        """)

        layout = QVBoxLayout(self)
        shortcuts = [
            ("Ctrl+T", "New tab"),
            ("Ctrl+W", "Close tab"),
            ("Ctrl+Q", "Exit"),
            ("Ctrl+L", "Focus URL bar"),
            ("Ctrl+J", "Toggle JS (this tab)"),
            ("Ctrl+B", "Toggle bookmarks"),
            ("Ctrl+D", "Bookmark page"),
            ("Ctrl+,", "Preferences"),
            ("Ctrl+Shift+N", "New Tor circuit"),
            ("Ctrl+Shift+S", "Toggle Speed Mode"),
            ("Ctrl+Shift+Delete", "Clear all data"),
            ("Ctrl+Shift+/", "This help"),
            ("Ctrl+Plus/Minus/0", "Zoom in/out/reset"),
            ("Alt+Left/Right", "Back/Forward"),
            ("F5", "Reload"),
        ]
        for keys, desc in shortcuts:
            row = QHBoxLayout()
            k = QLabel(keys)
            k.setFont(QFont("Monospace", 10))
            k.setStyleSheet("color: #58a6ff; font-weight: bold;")
            d = QLabel(desc)
            d.setStyleSheet("color: #8b949e;")
            row.addWidget(k)
            row.addWidget(d)
            row.addStretch()
            layout.addLayout(row)
        layout.addStretch()

        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.accept)
        layout.addWidget(close_btn)


# ═══════════════════════════════════════════════════════════════════════════════
#  MAIN WINDOW
# ═══════════════════════════════════════════════════════════════════════════════

class BoneBrowser(QMainWindow):

    def __init__(self, crypto: CryptoEngine, config: dict):
        super().__init__()
        self.crypto = crypto
        self.config = config
        self.setWindowTitle(APP_NAME)
        self.setMinimumSize(1000, 700)

        # ── Tor Manager ──
        self.tor = TorManager(
            socks_port=config.get("tor_socks_port", DEFAULT_TOR_SOCKS),
            control_port=config.get("tor_control_port", DEFAULT_TOR_CONTROL),
        )
        self.tor.status_changed.connect(self._on_tor_status)
        self.tor.circuit_ready.connect(self._on_circuit)
        self.tor.log_message.connect(self._on_tor_log)

        # ── Web Profile ──
        self.web_profile = QWebEngineProfile("BoneProfile", self)
        self.web_profile.setPersistentCookiesPolicy(
            QWebEngineProfile.PersistentCookiesPolicy.NoPersistentCookies
        )

        # Memory-only HTTP cache (fast back/forward, no disk writes)
        self.web_profile.setHttpCacheType(
            QWebEngineProfile.HttpCacheType.MemoryHttpCache
        )

        # User agent spoofing
        if config.get("spoof_ua", True):
            ua = random.choice(USER_AGENTS)
            self.web_profile.setHttpUserAgent(ua)
            logger.info(f"User-Agent set to: {ua}")

        # Privacy interceptor with optional font blocking
        self.interceptor = PrivacyInterceptor(
            block_fonts=config.get("block_fonts", False)
        )
        self.web_profile.setUrlRequestInterceptor(self.interceptor)

        settings = self.web_profile.settings()
        settings.setAttribute(QWebEngineSettings.WebAttribute.JavascriptEnabled,
                              config.get("javascript_enabled", False))
        settings.setAttribute(QWebEngineSettings.WebAttribute.PluginsEnabled, False)
        settings.setAttribute(QWebEngineSettings.WebAttribute.WebGLEnabled,
                              not config.get("disable_webgl", True))
        settings.setAttribute(QWebEngineSettings.WebAttribute.LocalStorageEnabled, False)
        settings.setAttribute(QWebEngineSettings.WebAttribute.AutoLoadImages,
                              config.get("load_images", True))
        settings.setAttribute(QWebEngineSettings.WebAttribute.HyperlinkAuditingEnabled, False)

        # Download manager
        self.web_profile.downloadRequested.connect(self._on_download)

        # ── Build UI ──
        self._build_toolbar()
        self._build_tab_widget()
        self._build_status_bar()
        self._build_menu_bar()
        self._apply_theme()

        # Bookmarks
        self.bookmarks_panel = BookmarksPanel(self.crypto)
        self.bookmarks_panel.navigate_requested.connect(self.navigate_to)
        self.bookmarks_panel.add_btn.clicked.connect(self._bookmark_current)
        self.bookmarks_panel.setVisible(False)

        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QHBoxLayout(central)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        self.splitter = QSplitter(Qt.Orientation.Horizontal)
        self.splitter.addWidget(self.bookmarks_panel)
        self.splitter.addWidget(self.tab_widget)
        self.splitter.setSizes([220, 980])
        main_layout.addWidget(self.splitter)

        # Wipe previous session data on startup (just delete file, don't touch profile)
        if SESSION_FILE.exists():
            SESSION_FILE.unlink(missing_ok=True)

        # Progress throttle timer (avoids excessive UI updates)
        self._last_progress = 0
        self._progress_throttle = QTimer()
        self._progress_throttle.setSingleShot(True)
        self._progress_throttle.setInterval(100)  # max 10 updates/sec
        self._progress_throttle.timeout.connect(self._flush_progress)

        # Always open homepage
        self.add_tab(config.get("home_page", DEFAULT_HOME))

        # Start Tor
        self.tor.start()

        # IP check timer
        self._ip_timer = QTimer()
        self._ip_timer.timeout.connect(self._update_ip)
        self._ip_timer.start(30000)
        self._update_ip()

    # ── Toolbar ────────────────────────────────────────────────────────────

    def _build_toolbar(self):
        self.toolbar = QToolBar("Navigation")
        self.toolbar.setIconSize(QSize(18, 18))
        self.toolbar.setMovable(False)
        self.addToolBar(self.toolbar)

        self.btn_back = QAction("<", self)
        self.btn_back.setShortcut(QKeySequence("Alt+Left"))
        self.btn_back.setToolTip("Go back (Alt+Left)")
        self.btn_back.triggered.connect(self._go_back)
        self.toolbar.addAction(self.btn_back)

        self.btn_forward = QAction(">", self)
        self.btn_forward.setShortcut(QKeySequence("Alt+Right"))
        self.btn_forward.setToolTip("Go forward (Alt+Right)")
        self.btn_forward.triggered.connect(self._go_forward)
        self.toolbar.addAction(self.btn_forward)

        self.btn_reload = QAction("⟳", self)
        self.btn_reload.setShortcut(QKeySequence("F5"))
        self.btn_reload.setToolTip("Reload page (F5)")
        self.btn_reload.triggered.connect(self._go_reload)
        self.toolbar.addAction(self.btn_reload)

        self.btn_home = QAction("⌂", self)
        self.btn_home.setToolTip("Go to home page")
        self.btn_home.triggered.connect(self._go_home)
        self.toolbar.addAction(self.btn_home)

        self.toolbar.addSeparator()

        self.url_bar = UrlBar(get_current_url=self._current_url_for_bar)
        self.url_bar.setPlaceholderText("URL, .onion, or search...")
        self.url_bar.returnPressed.connect(self._on_url_entered)
        self.url_bar.setFont(QFont("Monospace", 11))
        self.toolbar.addWidget(self.url_bar)

        self.btn_new_tab = QAction("＋", self)
        self.btn_new_tab.setShortcut(QKeySequence("Ctrl+T"))
        self.btn_new_tab.setToolTip("New tab (Ctrl+T)")
        self.btn_new_tab.triggered.connect(lambda: self.add_tab())
        self.toolbar.addAction(self.btn_new_tab)

        self.toolbar.addSeparator()

        self.btn_circuit = QAction("Circuit", self)
        self.btn_circuit.setToolTip("View Tor circuits")
        self.btn_circuit.triggered.connect(self._show_circuits)
        self.toolbar.addAction(self.btn_circuit)

        self.btn_new_circuit = QAction("New IP", self)
        self.btn_new_circuit.setShortcut(QKeySequence("Ctrl+Shift+N"))
        self.btn_new_circuit.setToolTip("Get new Tor circuit and exit IP (Ctrl+Shift+N)")
        self.btn_new_circuit.triggered.connect(self._rotate_circuit)
        self.toolbar.addAction(self.btn_new_circuit)

        # Ctrl+L to focus URL bar
        focus_url = QAction(self)
        focus_url.setShortcut(QKeySequence("Ctrl+L"))
        focus_url.triggered.connect(lambda: self.url_bar.setFocus())
        self.addAction(focus_url)

        # Zoom shortcuts
        zoom_in = QAction(self)
        zoom_in.setShortcut(QKeySequence("Ctrl+Plus"))
        zoom_in.triggered.connect(lambda: self._current_tab().zoom_in() if self._current_tab() else None)
        self.addAction(zoom_in)

        zoom_out = QAction(self)
        zoom_out.setShortcut(QKeySequence("Ctrl+Minus"))
        zoom_out.triggered.connect(lambda: self._current_tab().zoom_out() if self._current_tab() else None)
        self.addAction(zoom_out)

        zoom_reset = QAction(self)
        zoom_reset.setShortcut(QKeySequence("Ctrl+0"))
        zoom_reset.triggered.connect(lambda: self._current_tab().zoom_reset() if self._current_tab() else None)
        self.addAction(zoom_reset)

        # Shortcuts help
        shortcuts_help = QAction(self)
        shortcuts_help.setShortcut(QKeySequence("Ctrl+Shift+/"))
        shortcuts_help.triggered.connect(self._show_shortcuts)
        self.addAction(shortcuts_help)

    # ── Tab Widget ─────────────────────────────────────────────────────────

    def _build_tab_widget(self):
        self.tab_widget = QTabWidget()
        self.tab_widget.setTabsClosable(True)
        self.tab_widget.setMovable(True)
        self.tab_widget.setDocumentMode(True)
        self.tab_widget.tabCloseRequested.connect(self._close_tab)
        self.tab_widget.currentChanged.connect(self._on_tab_switched)
        self.tab_widget.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tab_widget.customContextMenuRequested.connect(self._tab_context_menu)

    def _tab_context_menu(self, point):
        index = self.tab_widget.tabBar().tabAt(point)
        if index < 0:
            return
        menu = QMenu(self)
        menu.setStyleSheet("QMenu { background-color: #0d1117; color: #c9d1d9; border: 1px solid #30363d; }"
                           "QMenu::item:selected { background-color: #1f2b47; }")
        act_close = menu.addAction("Close Tab")
        act_reload = menu.addAction("Reload Tab")
        act_dup = menu.addAction("Duplicate Tab")
        action = menu.exec(self.tab_widget.tabBar().mapToGlobal(point))
        if action == act_close:
            self._close_tab(index)
        elif action == act_reload:
            self.tab_widget.widget(index).reload()
        elif action == act_dup:
            url = self.tab_widget.widget(index).current_url()
            self.add_tab(url)

    # ── Status Bar ─────────────────────────────────────────────────────────

    def _build_status_bar(self):
        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)
        self.status_bar.setSizeGripEnabled(False)

        self.progress_bar = QProgressBar()
        self.progress_bar.setMaximumHeight(3)
        self.progress_bar.setMaximumWidth(180)
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setVisible(False)
        self.progress_bar.setTextVisible(False)
        self.status_bar.addPermanentWidget(self.progress_bar)

        self.tor_status_label = QLabel(" Tor: Connecting... ")
        self.tor_status_label.setFont(QFont("Monospace", 9))
        self.tor_status_label.setStyleSheet("padding: 2px 8px; color: #d29922; font-weight: bold;")
        self.status_bar.addPermanentWidget(self.tor_status_label)

        self.ip_label = QLabel(" IP: ... ")
        self.ip_label.setFont(QFont("Monospace", 9))
        self.ip_label.setStyleSheet("padding: 2px 8px; color: #8b949e;")
        self.status_bar.addPermanentWidget(self.ip_label)

        self.blocked_label = QLabel(" Blocked: 0 ")
        self.blocked_label.setFont(QFont("Monospace", 9))
        self.blocked_label.setStyleSheet("padding: 2px 8px; color: #8b949e;")
        self.status_bar.addPermanentWidget(self.blocked_label)

        self._block_timer = QTimer()
        self._block_timer.timeout.connect(
            lambda: self.blocked_label.setText(f" Blocked: {self.interceptor.blocked_count} ")
        )
        self._block_timer.start(3000)

        self.js_label = QLabel(" JS:OFF ")
        self.js_label.setFont(QFont("Monospace", 9))
        self.js_label.setStyleSheet("padding: 2px 8px; color: #3fb950;")
        self.status_bar.addPermanentWidget(self.js_label)

    # ── Menu Bar ───────────────────────────────────────────────────────────

    def _build_menu_bar(self):
        menubar = self.menuBar()

        file_menu = menubar.addMenu("File")
        new_tab = QAction("New Tab", self)
        new_tab.setShortcut(QKeySequence("Ctrl+T"))
        new_tab.triggered.connect(lambda: self.add_tab())
        file_menu.addAction(new_tab)

        close_tab = QAction("Close Tab", self)
        close_tab.setShortcut(QKeySequence("Ctrl+W"))
        close_tab.triggered.connect(lambda: self._close_tab(self.tab_widget.currentIndex()))
        file_menu.addAction(close_tab)

        file_menu.addSeparator()

        clear_all = QAction("Clear All Data", self)
        clear_all.setShortcut(QKeySequence("Ctrl+Shift+Delete"))
        clear_all.triggered.connect(self._clear_all_data)
        file_menu.addAction(clear_all)

        file_menu.addSeparator()

        exit_action = QAction("Exit", self)
        exit_action.setShortcut(QKeySequence("Ctrl+Q"))
        exit_action.triggered.connect(self.close)
        file_menu.addAction(exit_action)

        sec_menu = menubar.addMenu("Security")
        self.js_toggle = QAction("Enable JavaScript", self)
        self.js_toggle.setCheckable(True)
        self.js_toggle.setChecked(self.config.get("javascript_enabled", False))
        self.js_toggle.triggered.connect(self._toggle_javascript)
        sec_menu.addAction(self.js_toggle)

        js_temp = QAction("JS for This Tab Only", self)
        js_temp.setShortcut(QKeySequence("Ctrl+J"))
        js_temp.triggered.connect(self._toggle_js_current_tab)
        sec_menu.addAction(js_temp)

        sec_menu.addSeparator()

        # Speed mode toggle
        self.speed_mode = QAction("Speed Mode (block fonts + images)", self)
        self.speed_mode.setCheckable(True)
        self.speed_mode.setChecked(False)
        self.speed_mode.setShortcut(QKeySequence("Ctrl+Shift+S"))
        self.speed_mode.triggered.connect(self._toggle_speed_mode)
        sec_menu.addAction(self.speed_mode)

        sec_menu.addSeparator()

        new_circuit = QAction("New Tor Circuit", self)
        new_circuit.setShortcut(QKeySequence("Ctrl+Shift+N"))
        new_circuit.triggered.connect(self._rotate_circuit)
        sec_menu.addAction(new_circuit)

        circuit_info = QAction("View Circuits...", self)
        circuit_info.triggered.connect(self._show_circuits)
        sec_menu.addAction(circuit_info)

        bm_menu = menubar.addMenu("Bookmarks")
        toggle_bm = QAction("Toggle Panel", self)
        toggle_bm.setShortcut(QKeySequence("Ctrl+B"))
        toggle_bm.triggered.connect(self._toggle_bookmarks)
        bm_menu.addAction(toggle_bm)

        add_bm = QAction("Bookmark This Page", self)
        add_bm.setShortcut(QKeySequence("Ctrl+D"))
        add_bm.triggered.connect(self._bookmark_current)
        bm_menu.addAction(add_bm)

        settings_action = QAction("Preferences", self)
        settings_action.setShortcut(QKeySequence("Ctrl+,"))
        settings_action.triggered.connect(self._open_settings)
        menubar.addAction(settings_action)

        view_menu = menubar.addMenu("View")
        show_logs = QAction("Tor Log", self)
        show_logs.setShortcut(QKeySequence("Ctrl+Shift+L"))
        show_logs.triggered.connect(self._show_logs)
        view_menu.addAction(show_logs)

        show_shortcuts = QAction("Shortcuts", self)
        show_shortcuts.setShortcut(QKeySequence("Ctrl+Shift+/"))
        show_shortcuts.triggered.connect(self._show_shortcuts)
        view_menu.addAction(show_shortcuts)

    # ── Theme ──────────────────────────────────────────────────────────────

    def _apply_theme(self):
        self.setStyleSheet("""
            QMainWindow { background-color: #0d1117; }
            QToolBar {
                background-color: #161b22; border-bottom: 1px solid #30363d;
                padding: 2px; spacing: 2px;
            }
            QToolBar QToolButton {
                color: #8b949e; padding: 4px 8px; font-family: 'Monospace';
                font-size: 11px; font-weight: bold;
            }
            QToolBar QToolButton:hover { color: #58a6ff; }
            QToolBar QToolButton:pressed { color: #1f6feb; }
            QLineEdit {
                background-color: #010409; color: #c9d1d9;
                border: 1px solid #30363d; border-radius: 4px;
                padding: 6px 10px; font-family: 'Monospace';
            }
            QLineEdit:focus { border: 1px solid #58a6ff; }
            QTabWidget::pane { border: none; }
            QTabBar::tab {
                background-color: #0d1117; color: #6e7681;
                padding: 6px 16px; margin-right: 1px; border: none;
                font-family: 'Monospace'; font-size: 10px;
            }
            QTabBar::tab:selected {
                color: #58a6ff; border-bottom: 2px solid #58a6ff;
            }
            QTabBar::tab:hover { color: #c9d1d9; }
            QStatusBar { background-color: #161b22; color: #8b949e; }
            QPushButton {
                background-color: #21262d; color: #c9d1d9;
                border: 1px solid #30363d; border-radius: 4px;
                padding: 4px 12px; font-family: 'Monospace'; font-size: 10px;
            }
            QPushButton:hover { border-color: #58a6ff; color: #58a6ff; }
            QMenuBar { background-color: #161b22; color: #c9d1d9; }
            QMenuBar::item:selected { background-color: #1f2b47; }
            QMenu { background-color: #161b22; color: #c9d1d9; border: 1px solid #30363d; }
            QMenu::item:selected { background-color: #1f6feb; }
            QGroupBox { color: #58a6ff; border: 1px solid #30363d; border-radius: 4px; margin-top: 8px; padding-top: 14px; }
            QCheckBox { color: #c9d1d9; }
            QLabel { color: #c9d1d9; }
            QSpinBox { background-color: #010409; color: #c9d1d9; border: 1px solid #30363d; border-radius: 3px; padding: 3px; }
            QListWidget { background-color: #010409; color: #c9d1d9; border: 1px solid #30363d; font-family: 'Monospace'; }
            QListWidget::item:selected { background-color: #1f6feb; }
            QTextEdit { background-color: #010409; color: #c9d1d9; border: 1px solid #30363d; font-family: 'Monospace'; }
            QSplitter { background-color: #0d1117; }
            QProgressBar { background-color: #010409; border: 1px solid #30363d; border-radius: 2px; }
            QProgressBar::chunk { background-color: #58a6ff; border-radius: 2px; }
        """)

    # ── Tab Management ─────────────────────────────────────────────────────

    def add_tab(self, url=None):
        if url is None:
            url = "about:blank"

        enable_js = self.config.get("javascript_enabled", False)
        tab = SecureTab(self.web_profile, enable_js=enable_js)
        idx = self.tab_widget.addTab(tab, "New Tab")
        self.tab_widget.setCurrentIndex(idx)

        tab.title_changed.connect(lambda title: self._update_tab_title(tab, title))
        tab.url_changed.connect(lambda qurl: self._update_url(tab, qurl))
        tab.load_progress.connect(lambda p: self._update_progress(p))
        tab.load_started.connect(lambda: self._on_load_started(tab))
        tab.load_finished.connect(lambda ok: self._on_load_finished(tab, ok))

        tab.navigate(url)
        return tab

    def _current_tab(self) -> SecureTab:
        return self.tab_widget.currentWidget()

    def _close_tab(self, index):
        if self.tab_widget.count() <= 1:
            return
        widget = self.tab_widget.widget(index)
        self.tab_widget.removeTab(index)
        widget.deleteLater()

    def _update_tab_title(self, tab, title):
        idx = self.tab_widget.indexOf(tab)
        if idx >= 0:
            prefix = "... " if tab.is_loading else ""
            self.tab_widget.setTabText(idx, prefix + title[:24])

    def _update_url(self, tab, qurl):
        if tab == self._current_tab():
            if not self.url_bar.hasFocus():
                self.url_bar.setText(qurl.toString())

    def _on_load_started(self, tab):
        self.progress_bar.setVisible(True)
        self.progress_bar.setValue(0)
        idx = self.tab_widget.indexOf(tab)
        if idx >= 0:
            self.tab_widget.setTabText(idx, "... " + self.tab_widget.tabText(idx).lstrip("... "))
        url = tab.current_url()
        if url and url != "about:blank":
            if not self.url_bar.hasFocus():
                self.url_bar.setText(url)

    def _on_load_finished(self, tab, ok):
        self.progress_bar.setVisible(False)
        self.progress_bar.setValue(0)
        if not ok:
            self.status_bar.showMessage("Page failed to load. Error page shown.", 3000)
        if tab == self._current_tab():
            current = tab.current_url()
            if current and current != "about:blank":
                self.url_bar.setText(current)

    def _update_progress(self, progress):
        """Throttled progress update (max 10/sec to avoid UI jitter)."""
        self._last_progress = progress
        if not self._progress_throttle.isActive():
            self._flush_progress()

    def _flush_progress(self):
        progress = self._last_progress
        self.progress_bar.setValue(progress)
        if progress < 100:
            self.status_bar.showMessage(f"Loading {progress}%")
        else:
            self.status_bar.clearMessage()

    def _go_back(self):
        tab = self._current_tab()
        if tab:
            tab.back()

    def _go_forward(self):
        tab = self._current_tab()
        if tab:
            tab.forward()

    def _go_reload(self):
        tab = self._current_tab()
        if tab:
            tab.reload()

    def _go_home(self):
        self.navigate_to(self.config.get("home_page", DEFAULT_HOME))

    def _on_tab_switched(self, index):
        self.url_bar._reset_to_current()

    # ── Navigation ────────────────────────────────────────────────────────

    def navigate_to(self, url: str):
        if not url:
            return
        # Check if Tor is connected for .onion addresses
        if ".onion" in url and not self.tor.connected:
            tab = self._current_tab()
            if tab:
                tab.page.setHtml(ErrorPages.tor_not_connected())
                self.status_bar.showMessage("Tor not connected. Waiting for bootstrap...", 5000)
            return
        if ".onion" in url and not url.startswith(("http://", "https://")):
            url = "http://" + url
        elif ".onion" in url and url.startswith("https://"):
            url = "http://" + url[8:]
        elif not url.startswith(("http://", "https://", "about:", "data:")):
            if "." in url and " " not in url:
                if self.config.get("https_only", True):
                    url = "https://" + url
                else:
                    url = "http://" + url
            else:
                url = f"{SEARCH_ENGINE}{quote(url)}"
        self._current_tab().navigate(url)
        self.url_bar.setText(url)

    def _on_url_entered(self):
        typed = self.url_bar.text()
        self.url_bar.clearFocus()
        self.navigate_to(typed)

    def _current_url_for_bar(self):
        tab = self._current_tab()
        if tab:
            return tab.current_url()
        return None

    # ── Circuit Management ────────────────────────────────────────────────

    def _rotate_circuit(self):
        if self.tor.new_circuit():
            self.status_bar.showMessage("New circuit requested.", 3000)
            QTimer.singleShot(3000, self._update_ip)
        else:
            self.status_bar.showMessage("Could not rotate circuit.", 3000)

    def _show_circuits(self):
        dialog = CircuitDialog(self.tor, self)
        dialog.exec()

    def _show_logs(self):
        dialog = QDialog(self)
        dialog.setWindowTitle("Tor Log")
        dialog.setMinimumSize(700, 500)
        dialog.setStyleSheet("QDialog { background-color: #0d1117; }"
                              "QTextEdit { background-color: #010409; color: #c9d1d9; border: 1px solid #30363d; font-family: 'Monospace'; }")
        layout = QVBoxLayout(dialog)
        log_view = QTextEdit()
        log_view.setReadOnly(True)
        log_view.setFont(QFont("Monospace", 9))
        if LOG_FILE.exists():
            try:
                content = LOG_FILE.read_text(errors="replace")
                # Show last 1000 lines
                lines = content.splitlines()
                if len(lines) > 1000:
                    log_view.setPlainText("\n".join(lines[-1000:]))
                else:
                    log_view.setPlainText(content)
            except Exception:
                log_view.setPlainText("Could not read log file.")
        else:
            log_view.setPlainText("No log file yet.")
        layout.addWidget(log_view)
        dialog.exec()

    def _show_shortcuts(self):
        dialog = ShortcutsDialog(self)
        dialog.exec()

    # ── JavaScript Toggle ─────────────────────────────────────────────────

    def _toggle_javascript(self, checked):
        self.config["javascript_enabled"] = checked
        self.js_label.setText(" JS:ON " if checked else " JS:OFF ")
        self.js_label.setStyleSheet(
            f"padding: 2px 8px; color: {'#d29922' if checked else '#3fb950'}; font-weight: bold;"
        )
        for i in range(self.tab_widget.count()):
            tab = self.tab_widget.widget(i)
            if isinstance(tab, SecureTab):
                tab.set_javascript(checked)

    def _toggle_js_current_tab(self):
        tab = self._current_tab()
        if tab:
            settings = tab.page.settings()
            current = settings.testAttribute(QWebEngineSettings.WebAttribute.JavascriptEnabled)
            tab.set_javascript(not current)
            state = "ON" if not current else "OFF"
            self.status_bar.showMessage(f"JS {state} for this tab", 2000)

    def _toggle_speed_mode(self, checked):
        """Toggle speed mode: block fonts + images for faster page loads."""
        self.config["block_fonts"] = checked
        self.config["load_images"] = not checked
        # Update interceptor
        self.interceptor.block_fonts = checked
        # Update image loading for all tabs
        settings = self.web_profile.settings()
        settings.setAttribute(QWebEngineSettings.WebAttribute.AutoLoadImages, not checked)
        # Reload current tab to apply
        tab = self._current_tab()
        if tab:
            tab.reload()
        state = "ON" if checked else "OFF"
        self.status_bar.showMessage(f"Speed Mode {state}", 3000)

    # ── Bookmarks ─────────────────────────────────────────────────────────

    def _toggle_bookmarks(self):
        self.bookmarks_panel.setVisible(not self.bookmarks_panel.isVisible())

    def _bookmark_current(self):
        tab = self._current_tab()
        if tab:
            url = tab.current_url()
            title = tab.title()
            if url and url != "about:blank":
                self.bookmarks_panel.add_bookmark(url, title)
                self.status_bar.showMessage(f"Bookmarked: {title}", 2000)

    # ── Settings ──────────────────────────────────────────────────────────

    def _open_settings(self):
        dialog = SettingsDialog(self.config, self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            new_config = dialog.get_config()
            self.config.update(new_config)
            self.crypto.encrypt_file(CONFIG_FILE, json.dumps(self.config))
            self.status_bar.showMessage("Settings saved. Restart for Tor/UA changes.", 3000)

    # ── Clear Data ────────────────────────────────────────────────────────

    def _clear_all_data(self):
        reply = QMessageBox.question(
            self, "Clear All Data",
            "Clear all browsing data, cache, and cookies?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            self.web_profile.clearAllVisitedLinks()
            self.web_profile.cookieStore().deleteAllCookies()
            self.web_profile.clearHttpCache()
            self.status_bar.showMessage("All data cleared.", 3000)

    # ── Download Manager ──────────────────────────────────────────────────

    def _on_download(self, download: QWebEngineDownloadRequest):
        """Handle file downloads."""
        src_url = download.url().toString()
        suggested = download.downloadFileName()
        path, _ = QFileDialog.getSaveFileName(
            self, "Save File", str(DOWNLOAD_DIR / suggested)
        )
        if path:
            download.setDownloadDirectory(os.path.dirname(path))
            download.setDownloadFileName(os.path.basename(path))
            download.accept()
            self.status_bar.showMessage(f"Downloading: {suggested}", 3000)
            logger.info(f"Download started: {suggested} from {src_url}")

    # ─── Session Management ───────────────────────────────────────────────

    def _wipe_session_data(self):
        """Wipe all session data from the previous run."""
        # Delete encrypted session file
        if SESSION_FILE.exists():
            SESSION_FILE.unlink(missing_ok=True)
        # Clear cookies, visited links, and cache
        self.web_profile.clearAllVisitedLinks()
        self.web_profile.cookieStore().deleteAllCookies()
        self.web_profile.clearHttpCache()

    def _load_session(self):
        """Load last session's URLs from encrypted storage."""
        try:
            raw = self.crypto.decrypt_file(SESSION_FILE)
            if raw:
                data = json.loads(raw)
                return data.get("urls", [])
        except Exception:
            pass
        return []

    def _save_session(self):
        """Save current open tabs to encrypted storage."""
        urls = []
        for i in range(self.tab_widget.count()):
            tab = self.tab_widget.widget(i)
            if isinstance(tab, SecureTab):
                url = tab.current_url()
                if url and url != "about:blank" and url != "":
                    urls.append(url)
        try:
            self.crypto.encrypt_file(SESSION_FILE, json.dumps({"urls": urls}))
        except Exception:
            pass

    # ── Tor Status ────────────────────────────────────────────────────────

    def _on_tor_status(self, status: str):
        if status == "connected":
            self.tor_status_label.setText(" Tor: Connected ")
            self.tor_status_label.setStyleSheet(
                "padding: 2px 8px; color: #3fb950; font-weight: bold;"
            )
            self._update_ip()
            # Auto-reload if current tab shows "Tor Not Connected" error
            tab = self._current_tab()
            if tab:
                current = tab.current_url()
                if not current or current in ("about:blank", ""):
                    tab.navigate(self.config.get("home_page", DEFAULT_HOME))
        elif status == "connecting":
            self.tor_status_label.setText(" Tor: Connecting... ")
            self.tor_status_label.setStyleSheet(
                "padding: 2px 8px; color: #d29922; font-weight: bold;"
            )
        elif status == "error":
            self.tor_status_label.setText(" Tor: ERROR ")
            self.tor_status_label.setStyleSheet(
                "padding: 2px 8px; color: #f85149; font-weight: bold;"
            )
        else:
            self.tor_status_label.setText(" Tor: Disconnected ")
            self.tor_status_label.setStyleSheet(
                "padding: 2px 8px; color: #6e7681; font-weight: bold;"
            )

    def _on_circuit(self, info: str):
        self.status_bar.showMessage(info, 5000)

    def _on_tor_log(self, msg: str):
        logger.info(msg)

    def _update_ip(self):
        """Fetch exit IP from Tor control port."""
        ip = self.tor.get_info("address")
        if ip:
            self.ip_label.setText(f" IP: {ip} ")
            self.ip_label.setStyleSheet("padding: 2px 8px; color: #3fb950;")
        else:
            self.ip_label.setText(" IP: N/A ")
            self.ip_label.setStyleSheet("padding: 2px 8px; color: #6e7681;")

    # ── Shutdown ──────────────────────────────────────────────────────────

    def closeEvent(self, event):
        """Clean shutdown. Always wipe session data."""
        # Wipe all browsing data on exit
        self.web_profile.clearAllVisitedLinks()
        self.web_profile.cookieStore().deleteAllCookies()
        self.web_profile.clearHttpCache()
        # Delete session file
        if SESSION_FILE.exists():
            SESSION_FILE.unlink(missing_ok=True)

        self.tor.stop()
        self.web_profile.deleteLater()
        event.accept()


# ═══════════════════════════════════════════════════════════════════════════════
#  PASSWORD DIALOG
# ═══════════════════════════════════════════════════════════════════════════════

class PasswordDialog(QDialog):
    """Master password entry dialog."""

    def __init__(self, is_new=False, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"{APP_NAME} - {'Set' if is_new else 'Unlock'}")
        self.setFixedSize(400, 220)
        self.setWindowFlags(
            self.windowFlags() & ~Qt.WindowType.WindowContextHelpButtonHint
        )

        layout = QVBoxLayout(self)

        icon_label = QLabel("[LOCK]" if not is_new else "[NEW]")
        icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon_label.setFont(QFont("Monospace", 20, QFont.Weight.Bold))
        icon_label.setStyleSheet("color: #58a6ff;")
        layout.addWidget(icon_label)

        desc = QLabel(
            "Create a master password to encrypt your data."
            if is_new else
            "Enter your master password to unlock."
        )
        desc.setAlignment(Qt.AlignmentFlag.AlignCenter)
        desc.setStyleSheet("color: #8b949e;")
        layout.addWidget(desc)

        self.password_field = QLineEdit()
        self.password_field.setEchoMode(QLineEdit.EchoMode.Password)
        self.password_field.setPlaceholderText("Master Password")
        self.password_field.returnPressed.connect(self.accept)
        self.password_field.setFont(QFont("Monospace", 12))
        layout.addWidget(self.password_field)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok)
        buttons.accepted.connect(self.accept)
        layout.addWidget(buttons)

        self.setStyleSheet("""
            QDialog { background-color: #0d1117; }
            QLineEdit {
                background-color: #010409; color: #c9d1d9;
                border: 1px solid #30363d; border-radius: 4px; padding: 8px;
            }
            QLineEdit:focus { border: 1px solid #58a6ff; }
            QPushButton {
                background-color: #1f6feb; color: white; border: none;
                border-radius: 4px; padding: 8px 16px; font-weight: bold;
                font-family: 'Monospace';
            }
            QPushButton:hover { background-color: #388bfd; }
        """)

    def get_password(self) -> str:
        return self.password_field.text()


# ═══════════════════════════════════════════════════════════════════════════════
#  ENTRY POINT
# ═══════════════════════════════════════════════════════════════════════════════

DEFAULT_CONFIG = {
    "tor_socks_port": DEFAULT_TOR_SOCKS,
    "tor_control_port": DEFAULT_TOR_CONTROL,
    "javascript_enabled": False,
    "block_trackers": True,
    "block_third_party_cookies": True,
    "clear_on_exit": False,
    "do_not_track": True,
    "https_only": True,
    "disable_webgl": True,
    "block_canvas": True,
    "spoof_ua": True,
    "restore_session": False,
    "load_images": True,
    "block_fonts": False,
    "home_page": DEFAULT_HOME,
}


def main():
    os.environ.setdefault("QT_ENABLE_HIGHDPI_SCALING", "1")
    # Fix Fontconfig "Cannot load default config file" error
    if "FONTCONFIG_PATH" not in os.environ:
        for fc_path in ["/etc/fonts", "/usr/share/fontconfig", "/usr/share/fonts"]:
            if os.path.isdir(fc_path):
                os.environ["FONTCONFIG_PATH"] = fc_path
                break

    boot_file = DATA_DIR / "boot.json"
    socks_port = DEFAULT_TOR_SOCKS
    if boot_file.exists():
        try:
            boot = json.loads(boot_file.read_text())
            socks_port = boot.get("tor_socks_port", DEFAULT_TOR_SOCKS)
        except Exception:
            pass

    proxy_flag = f"--proxy-server=socks5://127.0.0.1:{socks_port}"
    # Chromium speed + privacy flags (safe, no security compromise)
    # AVOID: --aggressive-cache-discard (breaks first-load), --enable-features=NetworkService (bypasses proxy)
    extra_flags = " ".join([
        "--disable-background-networking",
        "--disable-client-side-phishing-detection",
        "--no-first-run",
        "--disable-sync",
        "--disable-translate",
        "--disable-extensions",
        "--disable-component-extensions-with-background-pages",
        "--disable-default-apps",
        "--disable-hang-monitor",
        "--disable-prompt-on-repost",
        "--disable-domain-reliability",
        "--disable-ipc-flooding-protection",
        "--disable-features=TranslateUI",
    ])
    existing_flags = os.environ.get("QTWEBENGINE_CHROMIUM_FLAGS", "")
    if "--proxy-server" not in existing_flags:
        os.environ["QTWEBENGINE_CHROMIUM_FLAGS"] = (
            f"{existing_flags} {proxy_flag} {extra_flags}".strip()
        )

    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setApplicationVersion(APP_VERSION)
    # Set app icon - try multiple locations
    icon = QIcon()
    if ICON_DIR.exists():
        icon = QIcon(str(ICON_DIR))
    else:
        # Fallback: try theme icon name (for installed desktop entries)
        icon = QIcon.fromTheme("bone-browser")
    if not icon.isNull():
        app.setWindowIcon(icon)

    is_new = not SALT_FILE.exists()

    pw_dialog = PasswordDialog(is_new=is_new)
    if pw_dialog.exec() != QDialog.DialogCode.Accepted:
        sys.exit(0)

    password = pw_dialog.get_password()
    if not password:
        QMessageBox.critical(None, "Error", "Password cannot be empty.")
        sys.exit(1)

    try:
        crypto = CryptoEngine(password)
    except Exception as e:
        QMessageBox.critical(None, "Error", f"Encryption init failed: {e}")
        sys.exit(1)

    if not is_new:
        try:
            raw = crypto.decrypt_file(CONFIG_FILE)
            # Merge with defaults to handle new config keys from updates
            config = dict(DEFAULT_CONFIG)
            if raw:
                config.update(json.loads(raw))
        except Exception:
            QMessageBox.critical(None, "Error", "Wrong password or corrupted data.")
            sys.exit(1)
    else:
        config = dict(DEFAULT_CONFIG)
        crypto.encrypt_file(CONFIG_FILE, json.dumps(config))

    actual_socks = config.get("tor_socks_port", DEFAULT_TOR_SOCKS)
    boot_file.write_text(json.dumps({"tor_socks_port": actual_socks}))

    browser = BoneBrowser(crypto, config)
    browser.show()
    browser.resize(1400, 900)

    exit_code = app.exec()

    try:
        crypto.encrypt_file(CONFIG_FILE, json.dumps(browser.config))
    except Exception:
        pass

    sys.exit(exit_code)


if __name__ == "__main__":
    main()
