#!/bin/bash
set -e

# Flockify Box Installation Script
# Run with: sudo bash scripts/install.sh

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$SCRIPT_DIR/.."
INSTALL_DIR=/home/pi/flockify

# Error handler
trap 'echo "ERROR: Installation failed at step. Check output above for details."; exit 1' ERR

# =============================================================================
# Step 1: Check prerequisites
# =============================================================================
echo ">>> Step 1: Checking prerequisites..."

if [ "$EUID" -ne 0 ]; then
    echo "ERROR: This script must be run as root (use sudo)."
    exit 1
fi

if ! grep -q "Raspberry Pi" /proc/device-tree/model 2>/dev/null; then
    echo "WARNING: This does not appear to be a Raspberry Pi."
    echo "Continuing anyway, but some steps may fail."
fi

echo "    Prerequisites OK."

# =============================================================================
# Step 2: Install system packages
# =============================================================================
echo ">>> Step 2: Installing system packages..."

apt-get update
apt-get install -y python3-pip python3-venv python3-pil python3-numpy \
    python3-spidev libmpv-dev pulseaudio pulseaudio-module-bluetooth \
    avahi-daemon python3-lgpio gpiod libgpiod-dev

echo "    System packages installed."

# =============================================================================
# Step 3: Install and configure Raspotify
# =============================================================================
echo ">>> Step 3: Installing Raspotify..."

curl -sL https://dtcooper.github.io/raspotify/install.sh | sh

echo "    Configuring Raspotify..."

RASPOTIFY_CONF="/etc/raspotify/conf"
if [ -f "$RASPOTIFY_CONF" ]; then
    # Update or add configuration values
    sed -i 's/^#*LIBRESPOT_NAME=.*/LIBRESPOT_NAME="flockifybox"/' "$RASPOTIFY_CONF"
    sed -i 's/^#*LIBRESPOT_BITRATE=.*/LIBRESPOT_BITRATE="96"/' "$RASPOTIFY_CONF"
    sed -i 's/^#*LIBRESPOT_BACKEND=.*/LIBRESPOT_BACKEND="pulseaudio"/' "$RASPOTIFY_CONF"

    # If the values weren't found and replaced, append them
    grep -q '^LIBRESPOT_NAME=' "$RASPOTIFY_CONF" || echo 'LIBRESPOT_NAME="flockifybox"' >> "$RASPOTIFY_CONF"
    grep -q '^LIBRESPOT_BITRATE=' "$RASPOTIFY_CONF" || echo 'LIBRESPOT_BITRATE="96"' >> "$RASPOTIFY_CONF"
    grep -q '^LIBRESPOT_BACKEND=' "$RASPOTIFY_CONF" || echo 'LIBRESPOT_BACKEND="pulseaudio"' >> "$RASPOTIFY_CONF"
else
    echo "WARNING: Raspotify config not found at $RASPOTIFY_CONF"
fi

systemctl restart raspotify
echo "    Raspotify installed and configured."

# =============================================================================
# Step 4: Set up project directory
# =============================================================================
echo ">>> Step 4: Setting up project directory..."

mkdir -p "$INSTALL_DIR"

# Copy project files from source to install directory
rsync -a --exclude='.git' --exclude='venv' --exclude='__pycache__' \
    --exclude='*.pyc' --exclude='node_modules' \
    "$PROJECT_DIR/" "$INSTALL_DIR/"

echo "    Project files copied to $INSTALL_DIR."

# =============================================================================
# Step 5: Create Python virtual environment
# =============================================================================
echo ">>> Step 5: Creating Python virtual environment..."

python3 -m venv --system-site-packages "$INSTALL_DIR/venv"
"$INSTALL_DIR/venv/bin/pip" install -r "$INSTALL_DIR/requirements.txt"

echo "    Virtual environment created and dependencies installed."

# =============================================================================
# Step 6: Create directories
# =============================================================================
echo ">>> Step 6: Creating directories..."

mkdir -p "$INSTALL_DIR/images/cache"

echo "    Directories created."

# =============================================================================
# Step 7: Set permissions
# =============================================================================
echo ">>> Step 7: Setting permissions..."

chown -R pi:pi "$INSTALL_DIR"

echo "    Permissions set."

# =============================================================================
# Step 8: Enable SPI
# =============================================================================
echo ">>> Step 8: Enabling SPI interface..."

raspi-config nonint do_spi 0

echo "    SPI enabled."

# =============================================================================
# Step 9: Set hostname
# =============================================================================
echo ">>> Step 9: Setting hostname..."

hostnamectl set-hostname flockifybox

echo "    Hostname set to flockifybox."

# =============================================================================
# Step 10: Add user to groups
# =============================================================================
echo ">>> Step 10: Adding pi user to required groups..."

usermod -aG spi,gpio,pulse,pulse-access,bluetooth pi

echo "    User added to groups."

# =============================================================================
# Step 11: Install systemd service
# =============================================================================
echo ">>> Step 11: Installing systemd service..."

cp "$INSTALL_DIR/systemd/flockify.service" /etc/systemd/system/
systemctl daemon-reload
systemctl enable flockify.service

echo "    Systemd service installed and enabled."

# =============================================================================
# Step 11b: Install low power mode service
# =============================================================================
echo ">>> Step 11b: Installing low power mode service..."

cp "$INSTALL_DIR/systemd/flockify-lowpower.service" /etc/systemd/system/
systemctl daemon-reload
systemctl enable flockify-lowpower.service
systemctl start flockify-lowpower.service || echo "    (will start on reboot)"

echo "    Low power mode service installed and enabled."
echo "    - CPU governor: powersave"
echo "    - HDMI output: disabled"
echo "    - WiFi power saving: enabled"
echo "    - Raspotify bitrate: 96 kbps"

# =============================================================================
# Step 11c: Install auto-update service + generate deploy key
# =============================================================================
echo ">>> Step 11c: Installing auto-update service..."

chmod +x "$INSTALL_DIR/scripts/auto-update.sh"
cp "$INSTALL_DIR/systemd/flockify-update.service" /etc/systemd/system/
systemctl daemon-reload
systemctl enable flockify-update.service

# Generate SSH deploy key for the pi user if it doesn't exist
DEPLOY_KEY=/home/pi/.ssh/flockify_deploy
if [ ! -f "$DEPLOY_KEY" ]; then
    echo "    Generating SSH deploy key for GitHub..."
    sudo -u pi mkdir -p /home/pi/.ssh
    sudo -u pi ssh-keygen -t ed25519 -N "" -f "$DEPLOY_KEY" -C "flockifybox-deploy"

    # Configure SSH to use this key for github.com
    SSH_CONFIG=/home/pi/.ssh/config
    if ! grep -q "flockify_deploy" "$SSH_CONFIG" 2>/dev/null; then
        sudo -u pi bash -c "cat >> $SSH_CONFIG" <<EOF

Host github.com
    HostName github.com
    User git
    IdentityFile ~/.ssh/flockify_deploy
    IdentitiesOnly yes
    StrictHostKeyChecking accept-new
EOF
        sudo -u pi chmod 600 "$SSH_CONFIG"
    fi

    # Switch the remote URL to SSH so the deploy key is used
    if [ -d "$INSTALL_DIR/.git" ]; then
        cd "$INSTALL_DIR"
        sudo -u pi git remote set-url origin git@github.com:NikBrownTRP/flockify-box.git || true
        cd - >/dev/null
    fi

    echo ""
    echo "    ============================================================"
    echo "    DEPLOY KEY GENERATED — ACTION REQUIRED"
    echo "    ============================================================"
    echo "    Add this public key to your GitHub repo as a deploy key:"
    echo "      https://github.com/NikBrownTRP/flockify-box/settings/keys/new"
    echo ""
    echo "    Key (copy the entire line below):"
    echo ""
    cat "${DEPLOY_KEY}.pub"
    echo ""
    echo "    Title: 'flockifybox-pi'   Access: read-only"
    echo "    ============================================================"
    echo ""
fi

echo "    Auto-update service installed and enabled."

# =============================================================================
# Step 12: Complete
# =============================================================================
echo ""
echo "========================================"
echo "Flockify Box installation complete!"
echo "========================================"
echo ""
echo "Next steps:"
echo "1. Reboot: sudo reboot"
echo "2. After reboot, open http://flockifybox.local:5000"
echo "3. Go to Settings and connect your Spotify account"
echo "4. Add playlists on the Playlists page"
echo ""
echo "To start manually: sudo systemctl start flockify"
echo "To view logs: journalctl -u flockify -f"
echo "========================================"
