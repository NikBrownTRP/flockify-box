#!/bin/bash
# Flockify Box — Auto-update from GitHub at boot
# Pulls latest main branch and reinstalls deps if requirements.txt changed.
# Runs before flockify.service via systemd dependency.
# Fails gracefully if offline or on any error so the box always boots.

set -u  # strict undefined-var check, but NOT set -e (we handle errors ourselves)

# Derive install dir from the script's own location so this works for any
# user/checkout (historical hardcoded /home/pi/flockify broke on boxes with
# a renamed default user).
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
INSTALL_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$INSTALL_DIR" || { echo "[auto-update] install dir missing"; exit 0; }

# Skip if offline (short timeout so boot isn't blocked)
if ! timeout 10 git ls-remote origin HEAD > /dev/null 2>&1; then
    echo "[auto-update] No network or remote unreachable, skipping"
    exit 0
fi

# Capture old state
OLD_HEAD=$(git rev-parse HEAD 2>/dev/null || echo "unknown")
OLD_REQS=""
if [ -f requirements.txt ]; then
    OLD_REQS=$(md5sum requirements.txt | awk '{print $1}')
fi

# Fast-forward pull only (never creates merge commits, refuses on divergence)
if ! timeout 30 git fetch origin main 2>&1; then
    echo "[auto-update] git fetch failed, keeping current version"
    exit 0
fi

if ! git merge --ff-only origin/main 2>&1; then
    echo "[auto-update] Fast-forward merge failed (local changes?), keeping current version"
    exit 0
fi

NEW_HEAD=$(git rev-parse HEAD)

if [ "$OLD_HEAD" = "$NEW_HEAD" ]; then
    echo "[auto-update] Already up to date at $NEW_HEAD"
    exit 0
fi

echo "[auto-update] Updated $OLD_HEAD -> $NEW_HEAD"

# Check if requirements.txt changed — if so, reinstall Python deps
if [ -f requirements.txt ]; then
    NEW_REQS=$(md5sum requirements.txt | awk '{print $1}')
    if [ "$OLD_REQS" != "$NEW_REQS" ]; then
        echo "[auto-update] requirements.txt changed, reinstalling Python dependencies"
        if [ -x "$INSTALL_DIR/venv/bin/pip" ]; then
            "$INSTALL_DIR/venv/bin/pip" install -r requirements.txt || \
                echo "[auto-update] pip install failed (continuing anyway)"
        fi
    fi
fi

echo "[auto-update] Update complete"
exit 0
