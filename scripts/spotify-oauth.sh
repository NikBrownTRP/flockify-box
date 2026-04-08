#!/bin/bash
# One-time Spotify OAuth setup for librespot/raspotify.
#
# Why this is needed:
#   librespot in discovery-only mode publishes itself via mDNS but only appears
#   in the Spotify Web API after a Spotify client on the same network has
#   connected to it. The connection only registers temporarily, so after a
#   reboot the device disappears from the API again — auto-resume on boot
#   doesn't work.
#
#   The fix is to log librespot in directly with cached OAuth credentials.
#   librespot 0.8 stores credentials in --system-cache (which raspotify points
#   at /var/lib/raspotify), and on subsequent runs uses them automatically as
#   long as LIBRESPOT_ENABLE_OAUTH is set in /etc/raspotify/conf.
#
# This script runs librespot interactively once with --enable-oauth, prints an
# OAuth URL for the user to authorize, saves the credentials to
# /var/lib/raspotify/credentials.json, then exits. After this, raspotify will
# pick up those credentials on every boot.
#
# Run with: sudo bash scripts/spotify-oauth.sh

set -u

if [ "$EUID" -ne 0 ]; then
    echo "ERROR: must be run as root (use sudo)."
    exit 1
fi

# Detect the user that owns the music box (the one running flockify)
RUNUSER=${SUDO_USER:-$(stat -c '%U' /home/*/flockify 2>/dev/null | head -1)}
if [ -z "$RUNUSER" ]; then
    echo "ERROR: could not determine which user runs flockify."
    echo "       Run as: sudo -u <user> bash scripts/spotify-oauth.sh"
    exit 1
fi
RUNUID=$(id -u "$RUNUSER")

CACHE=/var/cache/raspotify
SYSCACHE=/var/lib/raspotify

mkdir -p "$CACHE" "$SYSCACHE"
chown -R "$RUNUSER":"$RUNUSER" "$CACHE" "$SYSCACHE"

echo "============================================================"
echo "Spotify OAuth one-time setup for librespot"
echo "============================================================"
echo ""
echo "This will run librespot interactively. It will print a Spotify"
echo "authorization URL — open it in any browser and approve the request"
echo "with the SAME Spotify account the music box should use."
echo ""
echo "After authorization, librespot will save credentials and start"
echo "running. Watch for the line 'Authenticated as ...' then press"
echo "Ctrl+C to stop."
echo ""
echo "Stopping raspotify..."
systemctl stop raspotify 2>/dev/null || true

echo "Running librespot with --enable-oauth..."
echo ""
sudo -u "$RUNUSER" \
    XDG_RUNTIME_DIR=/run/user/"$RUNUID" \
    DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/"$RUNUID"/bus \
    /usr/bin/librespot \
    --name flockifybox \
    --backend alsa \
    --device default \
    --bitrate 96 \
    --cache "$CACHE" \
    --system-cache "$SYSCACHE" \
    --enable-oauth

# When the user Ctrl+Cs, we land here.
echo ""
echo "Stopping librespot. Verifying credentials..."

if [ ! -f "$SYSCACHE/credentials.json" ]; then
    # Older librespot versions might have written it to --cache instead
    if [ -f "$CACHE/credentials.json" ]; then
        echo "Moving credentials from $CACHE to $SYSCACHE..."
        mv "$CACHE/credentials.json" "$SYSCACHE/credentials.json"
        chown "$RUNUSER":"$RUNUSER" "$SYSCACHE/credentials.json"
    else
        echo "ERROR: credentials.json was not created. OAuth may have failed."
        echo "       Try running this script again."
        exit 1
    fi
fi

echo ""
echo "============================================================"
echo "OAuth setup complete!"
echo "============================================================"
echo "Credentials saved to: $SYSCACHE/credentials.json"
echo ""
echo "Starting raspotify..."
systemctl start raspotify
sleep 5

echo ""
echo "raspotify status:"
systemctl is-active raspotify
echo ""
echo "If everything worked, the music box should now be visible"
echo "as a persistent Spotify Connect device named 'flockifybox'"
echo "in your account, and auto-resume on boot will work."
