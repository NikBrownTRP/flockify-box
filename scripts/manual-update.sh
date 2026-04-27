#!/bin/bash
# Flockify Box — Manual update triggered from the web UI.
#
# Wraps auto-update.sh (which handles git pull + dep reinstall) and then
# restarts flockify.service so the new code is live. Designed to be invoked
# via sudo from the Flask app, typically through systemd-run so it survives
# the parent restart.
#
# Logs to journald — view with:
#   journalctl -t flockify-manual-update -f

set -u
TAG=flockify-manual-update
INSTALL_DIR=/home/pi/flockify

log() { logger -t "$TAG" -- "$1"; echo "[$TAG] $1"; }

log "Manual update started"

if [ ! -d "$INSTALL_DIR" ]; then
    log "Install dir missing: $INSTALL_DIR"
    exit 1
fi

# Run the existing auto-update script (does git fetch + ff-merge + pip).
# It always exits 0 on its own (graceful), so capture status separately.
if /bin/bash "$INSTALL_DIR/scripts/auto-update.sh"; then
    log "auto-update.sh completed"
else
    log "auto-update.sh failed (continuing to restart anyway)"
fi

# Restart the main service so the new code is loaded. We do NOT restart
# flockify-update (oneshot, only on boot). go-librespot picks up new config
# on its own service restart if needed; the main flockify service drives it.
log "Restarting flockify.service"
if systemctl restart flockify.service; then
    log "Restart complete"
else
    log "Restart failed"
    exit 2
fi

exit 0
