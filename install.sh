#!/bin/bash
# Bone Browser - Linux Installer
# Installs the app to ~/.local/share/bone-browser/ and adds it to the app menu

set -e

INSTALL_DIR="$HOME/.local/share/bone-browser"
DESKTOP_DIR="$HOME/.local/share/applications"
ICON_DIR="$HOME/.local/share/icons/hicolor"
BIN_DIR="$HOME/.local/bin"
SOURCE_DIR="$(cd "$(dirname "$0")" && pwd)"

echo "╔══════════════════════════════════════╗"
echo "║       Bone Browser Installer         ║"
echo "╚══════════════════════════════════════╝"
echo ""

# Check dependencies
echo "[1/6] Checking dependencies..."
if ! command -v python3 &>/dev/null; then
    echo "ERROR: python3 not found. Install Python 3.10+ first."
    exit 1
fi

if ! command -v tor &>/dev/null; then
    echo "WARNING: tor not found. Install with: sudo apt install tor"
fi

# Create directories
echo "[2/6] Creating directories..."
mkdir -p "$INSTALL_DIR"
mkdir -p "$DESKTOP_DIR"
mkdir -p "$ICON_DIR/16x16/apps"
mkdir -p "$ICON_DIR/32x32/apps"
mkdir -p "$ICON_DIR/48x48/apps"
mkdir -p "$ICON_DIR/256x256/apps"
mkdir -p "$BIN_DIR"

# Copy application files
echo "[3/6] Installing application..."
cp "$SOURCE_DIR/browser.py" "$INSTALL_DIR/"
cp "$SOURCE_DIR/run.sh" "$INSTALL_DIR/"
chmod +x "$INSTALL_DIR/run.sh"

# Install icons
echo "[4/6] Installing icons..."
cp "$SOURCE_DIR/icon_16.png" "$ICON_DIR/16x16/apps/bone-browser.png"
cp "$SOURCE_DIR/icon_32.png" "$ICON_DIR/32x32/apps/bone-browser.png"
cp "$SOURCE_DIR/icon_48.png" "$ICON_DIR/48x48/apps/bone-browser.png"
cp "$SOURCE_DIR/icon.png" "$ICON_DIR/256x256/apps/bone-browser.png"

# Install desktop entry
echo "[5/6] Installing desktop entry..."
cp "$SOURCE_DIR/bone-browser.desktop" "$DESKTOP_DIR/"
chmod +x "$DESKTOP_DIR/bone-browser.desktop"
# Update Exec path in the installed desktop file
sed -i "s|$HOME/.local/share/bone-browser/run.sh|$INSTALL_DIR/run.sh|g" "$DESKTOP_DIR/bone-browser.desktop"

# Create symlink in ~/.local/bin
echo "[6/6] Creating command-line shortcut..."
ln -sf "$INSTALL_DIR/run.sh" "$BIN_DIR/bone-browser"
chmod +x "$BIN_DIR/bone-browser"

# Update icon cache
if command -v gtk-update-icon-cache &>/dev/null; then
    gtk-update-icon-cache -f "$ICON_DIR" 2>/dev/null || true
fi

# Update desktop database
if command -v update-desktop-database &>/dev/null; then
    update-desktop-database "$DESKTOP_DIR" 2>/dev/null || true
fi

echo ""
echo "╔══════════════════════════════════════╗"
echo "║    Installation Complete!            ║"
echo "╚══════════════════════════════════════╝"
echo ""
echo "  App menu:  Search for 'Bone Browser'"
echo "  Terminal:  bone-browser"
echo "  Location:  $INSTALL_DIR"
echo ""
echo "  To uninstall: $INSTALL_DIR/uninstall.sh"
echo ""

# Create uninstaller
cat > "$INSTALL_DIR/uninstall.sh" << 'UNINSTALL'
#!/bin/bash
echo "Uninstalling Bone Browser..."
rm -f "$HOME/.local/share/applications/bone-browser.desktop"
rm -f "$HOME/.local/bin/bone-browser"
rm -f "$HOME/.local/share/icons/hicolor/16x16/apps/bone-browser.png"
rm -f "$HOME/.local/share/icons/hicolor/32x32/apps/bone-browser.png"
rm -f "$HOME/.local/share/icons/hicolor/48x48/apps/bone-browser.png"
rm -f "$HOME/.local/share/icons/hicolor/256x256/apps/bone-browser.png"
rm -rf "$HOME/.local/share/bone-browser"
echo "Bone Browser uninstalled. Data in ~/.bone-browser/ preserved."
UNINSTALL
chmod +x "$INSTALL_DIR/uninstall.sh"
