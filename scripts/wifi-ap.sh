#!/bin/bash
# Flockify Box WiFi AP — start a hotspot if no known WiFi connects.
#
# Run as a systemd oneshot Before=network-online.target. If wlan0 is
# already connected (normal boot), exits immediately. Otherwise waits
# up to WAIT_SECONDS for autoconnect, then creates a NetworkManager
# hotspot so the user can open the web UI and add WiFi credentials.
#
# The AP uses ipv4.method=shared which makes NetworkManager start an
# internal dnsmasq for DHCP/DNS — no extra packages needed.
#
# Installed to /etc/systemd/system/flockify-wifi-ap.service by
# scripts/install.sh.

set -euo pipefail

SSID="${FLOCKIFY_AP_SSID:-FlockifyBox}"
PSK="${FLOCKIFY_AP_PSK:-flockify123}"
CON_NAME="FlockifyAP"
FLAG_FILE="/run/flockify-ap-active"
WAIT_SECONDS=30
POLL_INTERVAL=5

# ----------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------

wifi_connected() {
    local state
    state=$(nmcli -t -f GENERAL.STATE device show wlan0 2>/dev/null | cut -d: -f2)
    [[ "$state" == *"connected"* ]] && [[ "$state" != *"disconnected"* ]]
}

# ----------------------------------------------------------------
# Main
# ----------------------------------------------------------------

rm -f "$FLAG_FILE"

# Already connected? Nothing to do.
if wifi_connected; then
    echo "[wifi-ap] WiFi already connected — no AP needed"
    exit 0
fi

# Wait for NetworkManager autoconnect (known networks in range).
echo "[wifi-ap] No WiFi connection, waiting ${WAIT_SECONDS}s for autoconnect..."
elapsed=0
while [ "$elapsed" -lt "$WAIT_SECONDS" ]; do
    sleep "$POLL_INTERVAL"
    elapsed=$((elapsed + POLL_INTERVAL))
    if wifi_connected; then
        echo "[wifi-ap] WiFi connected after ${elapsed}s"
        exit 0
    fi
done

# Still no connection — start the AP.
echo "[wifi-ap] No WiFi after ${WAIT_SECONDS}s — starting AP (SSID: $SSID)"

# Remove stale AP profile from a previous boot (idempotent).
nmcli connection delete "$CON_NAME" 2>/dev/null || true

# Create and activate the hotspot.
nmcli connection add type wifi ifname wlan0 con-name "$CON_NAME" \
    autoconnect no ssid "$SSID" \
    wifi.mode ap wifi.band bg wifi.channel 6 \
    ipv4.method shared ipv4.addresses 192.168.4.1/24 \
    wifi-sec.key-mgmt wpa-psk wifi-sec.psk "$PSK"

nmcli connection up "$CON_NAME"

# Disable WiFi power save while in AP mode — it causes packet loss
# for connected clients on the Pi 5's CYW43455 chip.
iw dev wlan0 set power_save off 2>/dev/null || true

# Signal to flockify that we're in AP mode so the web UI can show
# a "Hotspot Active — connect to your home WiFi" banner.
touch "$FLAG_FILE"

echo "[wifi-ap] AP active at 192.168.4.1 (SSID: $SSID)"
