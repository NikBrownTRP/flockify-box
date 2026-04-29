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
# Step 3: Install go-librespot (Spotify Connect)
# =============================================================================
echo ">>> Step 3: Installing go-librespot..."

ARCH=$(dpkg --print-architecture)
GO_LIBRESPOT_URL="https://github.com/devgianlu/go-librespot/releases/latest/download/go-librespot_linux_${ARCH}.tar.gz"
INSTALL_USER=$(logname 2>/dev/null || echo pi)

if [ ! -f /usr/local/bin/go-librespot ]; then
    echo "    Downloading go-librespot for ${ARCH}..."
    curl -sL "$GO_LIBRESPOT_URL" -o /tmp/go-librespot.tar.gz
    tar xzf /tmp/go-librespot.tar.gz -C /tmp go-librespot
    mv /tmp/go-librespot /usr/local/bin/go-librespot
    chmod +x /usr/local/bin/go-librespot
    rm -f /tmp/go-librespot.tar.gz
    echo "    go-librespot binary installed."
else
    echo "    go-librespot binary already present, skipping download."
fi

mkdir -p /etc/go-librespot
cp "$PROJECT_DIR/config/go-librespot.yml" /etc/go-librespot/config.yml
chown -R "$INSTALL_USER:$INSTALL_USER" /etc/go-librespot

# Remove raspotify if present (replaced by go-librespot)
if systemctl is-active raspotify >/dev/null 2>&1 || systemctl is-enabled raspotify >/dev/null 2>&1; then
    echo "    Removing raspotify (replaced by go-librespot)..."
    systemctl stop raspotify 2>/dev/null || true
    systemctl disable raspotify 2>/dev/null || true
    rm -f /etc/systemd/system/raspotify.service.d/override.conf
    rm -f /etc/sudoers.d/flockify-raspotify
fi

cp "$PROJECT_DIR/systemd/go-librespot.service" /etc/systemd/system/
systemctl daemon-reload
systemctl enable go-librespot

echo "    go-librespot installed and enabled."

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
# Step 8b: Enable I²S DAC (MAX98357A)
# =============================================================================
echo ">>> Step 8b: Enabling I²S DAC overlay for MAX98357A..."

CONFIG_TXT="/boot/firmware/config.txt"
if [ ! -f "$CONFIG_TXT" ]; then
    CONFIG_TXT="/boot/config.txt"
fi

if [ -f "$CONFIG_TXT" ]; then
    # Append I²S + hifiberry-dac overlay (MAX98357A presents as hifiberry-dac).
    # Idempotent — only add if the line is not already present.
    grep -q '^dtparam=i2s=on' "$CONFIG_TXT" || echo 'dtparam=i2s=on' >> "$CONFIG_TXT"
    grep -q '^dtoverlay=hifiberry-dac' "$CONFIG_TXT" || echo 'dtoverlay=hifiberry-dac' >> "$CONFIG_TXT"
    echo "    I²S DAC overlay enabled (will take effect on next reboot)."
else
    echo "    WARNING: could not find config.txt — enable dtoverlay=hifiberry-dac manually."
fi

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

usermod -aG spi,gpio,pulse,pulse-access,bluetooth,input pi

echo "    User added to groups."

# =============================================================================
# Step 11: Install systemd service
# =============================================================================
echo ">>> Step 11: Installing systemd service..."

cp "$INSTALL_DIR/systemd/flockify.service" /etc/systemd/system/
cp "$INSTALL_DIR/systemd/flockify-boot-splash.service" /etc/systemd/system/
systemctl daemon-reload
systemctl enable flockify.service
systemctl enable flockify-boot-splash.service

echo "    Systemd service installed and enabled."
echo "    Boot splash service installed (shows image early in boot)."

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
echo "    - go-librespot bitrate: 320 kbps"

# =============================================================================
# Step 11b2: Configure EEPROM POWER_OFF_ON_HALT (Pi 4/5 only)
# =============================================================================
echo ">>> Step 11b2: Configuring EEPROM POWER_OFF_ON_HALT=1..."

if command -v rpi-eeprom-config >/dev/null 2>&1; then
    CURRENT_EEPROM=$(rpi-eeprom-config 2>/dev/null || true)
    if echo "$CURRENT_EEPROM" | grep -q '^POWER_OFF_ON_HALT=1'; then
        echo "    POWER_OFF_ON_HALT=1 already set — skipping."
    else
        EEPROM_TMP=$(mktemp)
        if echo "$CURRENT_EEPROM" | grep -q '^POWER_OFF_ON_HALT'; then
            # Key exists with a different value — replace it
            echo "$CURRENT_EEPROM" | sed 's/^POWER_OFF_ON_HALT=.*/POWER_OFF_ON_HALT=1/' > "$EEPROM_TMP"
        else
            # Key absent — append it
            echo "$CURRENT_EEPROM" > "$EEPROM_TMP"
            echo 'POWER_OFF_ON_HALT=1' >> "$EEPROM_TMP"
        fi
        if rpi-eeprom-config --apply "$EEPROM_TMP"; then
            rm -f "$EEPROM_TMP"
            echo "    EEPROM updated: POWER_OFF_ON_HALT=1"
            echo "    *** A reboot is required for this change to take effect. ***"
            echo "    After reboot: pressing J2 will cut all Pi power rails on halt."
            echo "    The powerbank will auto-shutoff when current drops to near-zero."
        else
            rm -f "$EEPROM_TMP"
            echo "    WARNING: rpi-eeprom-config --apply failed — EEPROM not updated."
            echo "    Run 'sudo rpi-eeprom-config --edit' manually and add: POWER_OFF_ON_HALT=1"
        fi
    fi
else
    echo "    rpi-eeprom-config not found — EEPROM step skipped (Pi 3/Zero)."
fi

# =============================================================================
# Step 11b3: Install WiFi AP hotspot service
# =============================================================================
echo ">>> Step 11b3: Installing WiFi AP hotspot service..."

chmod +x "$INSTALL_DIR/scripts/wifi-ap.sh"
cp "$INSTALL_DIR/systemd/flockify-wifi-ap.service" /etc/systemd/system/
systemctl daemon-reload
systemctl enable flockify-wifi-ap.service

echo "    WiFi AP hotspot service installed and enabled."
echo "    If no known WiFi connects within 30s of boot, the box creates"
echo "    a 'FlockifyBox' hotspot for WiFi configuration via the web UI."

# =============================================================================
# Step 11c: Install auto-update service + generate deploy key
# =============================================================================
echo ">>> Step 11c: Installing auto-update service..."

chmod +x "$INSTALL_DIR/scripts/auto-update.sh"
chmod +x "$INSTALL_DIR/scripts/manual-update.sh"
cp "$INSTALL_DIR/systemd/flockify-update.service" /etc/systemd/system/
systemctl daemon-reload
systemctl enable flockify-update.service

# Install sudoers drop-in so the web UI can trigger manual-update.sh +
# the systemd-run wrapper without a password. The user and install path
# get substituted into the template — this works for any default-user
# rename (pi, nbrown, etc.) and any checkout location.
SUDOERS_TPL="$INSTALL_DIR/scripts/flockify-update.sudoers.template"
SUDOERS_DST=/etc/sudoers.d/flockify-update
# Determine which user the flockify service runs as. Prefer the existing
# unit's User= directive, fall back to the directory owner of the checkout.
FLOCKIFY_USER=$(systemctl show flockify.service -p User --value 2>/dev/null)
if [ -z "$FLOCKIFY_USER" ] || [ "$FLOCKIFY_USER" = "root" ]; then
    FLOCKIFY_USER=$(stat -c '%U' "$INSTALL_DIR")
fi
if [ -f "$SUDOERS_TPL" ] && [ -n "$FLOCKIFY_USER" ]; then
    SUDOERS_TMP=$(mktemp)
    sed -e "s|__FLOCKIFY_USER__|$FLOCKIFY_USER|g" \
        -e "s|__FLOCKIFY_DIR__|$INSTALL_DIR|g" \
        "$SUDOERS_TPL" > "$SUDOERS_TMP"
    if visudo -cf "$SUDOERS_TMP" >/dev/null; then
        install -m 0440 -o root -g root "$SUDOERS_TMP" "$SUDOERS_DST"
        echo "    Installed sudoers drop-in for manual updates (user=$FLOCKIFY_USER)."
    else
        echo "    WARNING: sudoers drop-in failed validation, not installing."
    fi
    rm -f "$SUDOERS_TMP"
fi

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
echo "   IMPORTANT: log into Spotify in your browser as the SAME account"
echo "   the music box should use (e.g. your child's account) before clicking"
echo "   'Connect to Spotify'."
echo "4. Add playlists on the Playlists page"
echo ""
echo "5. NOTE about the Spotify Developer App:"
echo "   If your music box uses a different Spotify account than the one"
echo "   that owns the Developer App, you must add that account to the app's"
echo "   User Management allowlist on https://developer.spotify.com/dashboard"
echo "   (Apps in Development Mode only allow whitelisted users.)"
echo ""
echo "To start manually: sudo systemctl start flockify"
echo "To view logs: journalctl -u flockify -f"
echo "========================================"
