# go-librespot Migration Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Replace raspotify + spotipy playback control with go-librespot's local HTTP API, eliminating the Spotify Web API dependency for play/pause/skip/volume.

**Architecture:** go-librespot runs as a systemd service, exposes a local HTTP API on port 3678. `spotify_manager.py` calls `localhost:3678` for all playback actions. spotipy is retained ONLY for read-only metadata (playlist info, cover art). All self-heal/rate-limit/recovery code is deleted.

**Tech Stack:** go-librespot (Go binary), requests (Python HTTP), spotipy (read-only metadata), systemd, nmcli

---

### Task 1: Install go-librespot binary + config on Pi

**Files:**
- Create: `systemd/go-librespot.service`
- Create: `config/go-librespot.yml`
- Modify: `scripts/install.sh`

**Step 1: Create go-librespot systemd service**

Create `systemd/go-librespot.service`:

```ini
[Unit]
Description=go-librespot (Spotify Connect)
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=pi
ExecStartPre=/bin/sleep 5
ExecStart=/usr/local/bin/go-librespot -config_dir /etc/go-librespot
Restart=on-failure
RestartSec=10
Environment=XDG_RUNTIME_DIR=/run/user/1000
Environment=DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/1000/bus

[Install]
WantedBy=multi-user.target
```

**Step 2: Create go-librespot config**

Create `config/go-librespot.yml`:

```yaml
device_name: flockifybox
device_type: speaker

zeroconf_enabled: true
credentials:
  type: zeroconf

audio_backend: alsa
audio_device: default
bitrate: 320
volume_steps: 100
initial_volume: 100

normalisation_disabled: false
normalisation_pregain: -3

server:
  enabled: true
  address: 127.0.0.1
  port: 3678
```

**Step 3: Update install.sh — replace raspotify section**

Replace the raspotify install block (Step 3 in install.sh) with go-librespot:

```bash
# Step 3: Install go-librespot
echo ">>> Step 3: Installing go-librespot..."

ARCH=$(dpkg --print-architecture)
GO_LIBRESPOT_VERSION="v0.2.0"
GO_LIBRESPOT_URL="https://github.com/devgianlu/go-librespot/releases/download/${GO_LIBRESPOT_VERSION}/go-librespot_linux_${ARCH}"

curl -sL "$GO_LIBRESPOT_URL" -o /usr/local/bin/go-librespot
chmod +x /usr/local/bin/go-librespot

mkdir -p /etc/go-librespot
cp "$PROJECT_DIR/config/go-librespot.yml" /etc/go-librespot/config.yml
# Fix device name in config
sed -i "s|device_name:.*|device_name: flockifybox|" /etc/go-librespot/config.yml

cp "$PROJECT_DIR/systemd/go-librespot.service" /etc/systemd/system/
# Replace pi user with actual user
sed -i "s|User=pi|User=$(logname 2>/dev/null || echo pi)|" /etc/systemd/system/go-librespot.service
systemctl daemon-reload
systemctl enable go-librespot

echo "    go-librespot installed and enabled."
```

Also remove the raspotify override + sudoers installation lines.

Also update the flockify.service `After=` line to depend on `go-librespot.service` instead of `raspotify.service`.

**Step 4: Deploy to Pi and test standalone**

```bash
# On Pi via SSH:
cd ~/flockify && git pull
sudo bash -c '
  ARCH=$(dpkg --print-architecture)
  curl -sL "https://github.com/devgianlu/go-librespot/releases/latest/download/go-librespot_linux_${ARCH}" -o /usr/local/bin/go-librespot
  chmod +x /usr/local/bin/go-librespot
  mkdir -p /etc/go-librespot
  cp config/go-librespot.yml /etc/go-librespot/config.yml
  sed -i "s|User=pi|User=nbrown|" systemd/go-librespot.service
  cp systemd/go-librespot.service /etc/systemd/system/
  systemctl daemon-reload
  systemctl enable go-librespot
  systemctl start go-librespot
'
sleep 5
curl -s http://127.0.0.1:3678/status
# Should return JSON with device info
```

Then pair from phone: Spotify app → Connect to device → flockifybox.
Then test local API:

```bash
curl -s http://127.0.0.1:3678/status | python3 -m json.tool
# Should show connected user, device name
```

**Step 5: Commit**

```bash
git add systemd/go-librespot.service config/go-librespot.yml scripts/install.sh
git commit -m "feat: add go-librespot service + config, replace raspotify in installer"
```

---

### Task 2: Rewrite spotify_manager.py — local API for playback

**Files:**
- Rewrite: `spotify_manager.py`
- Test: `tests/test_spotify_manager.py`

**Step 1: Write failing tests for the new local-API methods**

Replace existing playback tests in `tests/test_spotify_manager.py` with tests that mock `requests.post`/`requests.get` to `localhost:3678`:

```python
from unittest.mock import patch, MagicMock
import pytest

# Test play_playlist calls local API
@patch('spotify_manager.requests.post')
def test_play_playlist_calls_local_api(mock_post):
    mock_post.return_value = MagicMock(status_code=200)
    sm = _create_configured_manager()
    result = sm.play_playlist("spotify:playlist:abc123")
    mock_post.assert_called_once_with(
        "http://127.0.0.1:3678/player/play",
        json={"uri": "spotify:playlist:abc123"},
        timeout=5,
    )
    assert result is True

# Test play_playlist returns False on connection error
@patch('spotify_manager.requests.post')
def test_play_playlist_connection_error(mock_post):
    mock_post.side_effect = requests.ConnectionError()
    sm = _create_configured_manager()
    result = sm.play_playlist("spotify:playlist:abc123")
    assert result is False

# Test next_track
@patch('spotify_manager.requests.post')
def test_next_track_calls_local_api(mock_post):
    mock_post.return_value = MagicMock(status_code=200)
    sm = _create_configured_manager()
    assert sm.next_track() is True
    mock_post.assert_called_with(
        "http://127.0.0.1:3678/player/next", timeout=5,
    )

# Test get_current_track parses go-librespot status
@patch('spotify_manager.requests.get')
def test_get_current_track_parses_status(mock_get):
    mock_get.return_value = MagicMock(
        status_code=200,
        json=lambda: {
            "track": {
                "name": "Test Song",
                "artist_names": ["Artist A"],
                "album_name": "Test Album",
                "album_cover_url": "https://example.com/cover.jpg",
            },
            "paused": False,
        }
    )
    sm = _create_configured_manager()
    track = sm.get_current_track()
    assert track["name"] == "Test Song"
    assert track["artist"] == "Artist A"
    assert track["is_playing"] is True

# Test is_connected checks local API health
@patch('spotify_manager.requests.get')
def test_is_connected_true(mock_get):
    mock_get.return_value = MagicMock(status_code=200)
    sm = _create_configured_manager()
    assert sm.is_connected() is True

@patch('spotify_manager.requests.get')
def test_is_connected_false_on_error(mock_get):
    mock_get.side_effect = requests.ConnectionError()
    sm = _create_configured_manager()
    assert sm.is_connected() is False
```

**Step 2: Run tests to verify they fail**

```bash
python3 -m pytest tests/test_spotify_manager.py -v --tb=short
```

Expected: FAIL (old SpotifyManager doesn't have local API calls)

**Step 3: Rewrite spotify_manager.py**

The new SpotifyManager has two backends:
- `requests` → `localhost:3678` for playback (play, pause, next, prev, volume, status)
- `spotipy` → Spotify Web API for metadata only (get_playlist_info, OAuth flow)

```python
import requests
import spotipy
from spotipy.oauth2 import SpotifyOAuth

GO_LIBRESPOT_URL = "http://127.0.0.1:3678"
SCOPES = "playlist-read-private user-read-currently-playing"
TOKEN_CACHE_PATH = ".spotify_token_cache"


class SpotifyManager:
    """Spotify integration via go-librespot local API + spotipy metadata."""

    def __init__(self, config_manager):
        self.config = config_manager
        self.sp = None  # spotipy client for metadata only
        if self.is_configured():
            try:
                self._init_client()
            except Exception as e:
                print(f"[SpotifyManager] Failed to init spotipy: {e}")

    # -- Config / Auth (unchanged) --
    def is_configured(self): ...
    def has_credentials(self): ...
    def logout(self): ...
    def clear_credentials(self): ...
    def reauth_url(self): ...
    def _init_client(self): ...
    def get_auth_url(self, client_id, client_secret): ...
    def handle_callback(self, code): ...

    # -- Playback via local API (NEW) --
    def _local_post(self, path, json=None):
        try:
            r = requests.post(f"{GO_LIBRESPOT_URL}{path}",
                              json=json, timeout=5)
            return r.status_code < 300
        except Exception as e:
            print(f"[SpotifyManager] Local API error: {e}")
            return False

    def play_playlist(self, uri, **_kwargs):
        return self._local_post("/player/play", json={"uri": uri})

    def next_track(self):
        return self._local_post("/player/next")

    def previous_track(self):
        return self._local_post("/player/prev")

    def pause(self):
        return self._local_post("/player/pause")

    def resume(self):
        return self._local_post("/player/resume")

    def set_volume(self, level):
        return self._local_post("/player/volume",
                                json={"volume": max(0, min(100, int(level)))})

    def get_current_track(self):
        try:
            r = requests.get(f"{GO_LIBRESPOT_URL}/status", timeout=5)
            if r.status_code != 200:
                return None
            data = r.json()
            track = data.get("track")
            if not track:
                return None
            return {
                "name": track.get("name", ""),
                "artist": ", ".join(track.get("artist_names", [])),
                "album": track.get("album_name", ""),
                "album_art_url": track.get("album_cover_url", ""),
                "is_playing": not data.get("paused", True),
            }
        except Exception:
            return None

    def is_connected(self):
        try:
            r = requests.get(f"{GO_LIBRESPOT_URL}/status", timeout=3)
            return r.status_code == 200
        except Exception:
            return False

    # -- Metadata via spotipy (unchanged) --
    def get_playlist_info(self, uri): ...
```

**Step 4: Run tests to verify they pass**

```bash
python3 -m pytest tests/test_spotify_manager.py -v --tb=short
```

**Step 5: Commit**

```bash
git add spotify_manager.py tests/test_spotify_manager.py
git commit -m "feat: rewrite SpotifyManager to use go-librespot local API

Playback control (play/pause/next/prev/volume/status) now goes to
localhost:3678 instead of the Spotify Web API. spotipy retained for
read-only metadata only. All self-heal/rate-limit/recovery code deleted."
```

---

### Task 3: Simplify state_machine.py

**Files:**
- Modify: `state_machine.py`
- Test: `tests/test_state_machine.py`

**Step 1: Remove boot_resume flag, sink-input boosts, spirc pinning**

In `_activate_mode()`:
- Remove `boot_resume` parameter
- Remove `spotify.set_volume(100)` pinning
- Remove the sink-input boost thread
- Keep `self._apply_volume(self.volume)` (PipeWire sink control)
- Keep `spotify.play_playlist(uri)` (now hits local API)

In `get_status()`:
- Remove `spotify_needs_pairing` field

**Step 2: Run tests**

```bash
python3 -m pytest tests/test_state_machine.py -v --tb=short
```

**Step 3: Commit**

```bash
git add state_machine.py tests/test_state_machine.py
git commit -m "simplify: remove boot_resume, sink-input boosts, pairing flag from state_machine"
```

---

### Task 4: Simplify flockify.py

**Files:**
- Modify: `flockify.py`

**Step 1: Remove raspotify-specific code**

- Remove `on_pairing_required` callback wiring (lines 260-282)
- Remove the fallback SpotifyManager init with `_rate_limit_until`, `_stuck_failures`, etc. (lines 249-256)
- Simplify boot resume: just call `state_machine._activate_mode()` (no `boot_resume=True`)
- Update flockify.service dependency: `raspotify.service` → `go-librespot.service`

**Step 2: Test manually**

```bash
sudo systemctl restart flockify
curl -s http://localhost:5000/api/status | python3 -m json.tool
```

**Step 3: Commit**

```bash
git add flockify.py systemd/flockify.service
git commit -m "simplify: remove raspotify-specific init, pairing callback, boot_resume flag"
```

---

### Task 5: Update web/app.py — remove reset_pairing endpoint

**Files:**
- Modify: `web/app.py`
- Modify: `web/templates/settings.html`
- Modify: `web/static/js/app.js`

**Step 1: Remove `/api/spotify/reset_pairing` route**

The reset_pairing concept no longer exists — go-librespot handles its own sessions.

Remove the route, the JS `resetPairing()` function, and the "Reset Spotify Pairing" button from settings.html.

Keep: all other Spotify routes (connect, reauth, logout, clear) — these manage the spotipy OAuth for metadata.

**Step 2: Commit**

```bash
git add web/app.py web/templates/settings.html web/static/js/app.js
git commit -m "remove: reset_pairing endpoint + UI (no longer needed with go-librespot)"
```

---

### Task 6: Clean up deleted files

**Files:**
- Delete: `systemd/raspotify-override.conf`
- Delete: `systemd/flockify-raspotify.sudoers`
- Delete: `scripts/spotify-oauth.sh`
- Delete: `scripts/flockify-backlight-off` (move to install.sh if needed)

**Step 1: Remove files**

```bash
git rm systemd/raspotify-override.conf
git rm systemd/flockify-raspotify.sudoers
git rm scripts/spotify-oauth.sh
```

**Step 2: Commit**

```bash
git commit -m "cleanup: remove raspotify override, sudoers, oauth script"
```

---

### Task 7: Update install.sh — remove raspotify, add go-librespot uninstall

**Files:**
- Modify: `scripts/install.sh`

**Step 1: Add raspotify removal to installer**

For existing installs that have raspotify, add an uninstall step:

```bash
# Remove raspotify if present (replaced by go-librespot)
if systemctl is-active raspotify >/dev/null 2>&1; then
    echo "    Removing raspotify (replaced by go-librespot)..."
    systemctl stop raspotify
    systemctl disable raspotify
    rm -f /etc/systemd/system/raspotify.service.d/override.conf
    rm -f /etc/sudoers.d/flockify-raspotify
fi
```

**Step 2: Commit**

```bash
git add scripts/install.sh
git commit -m "installer: remove raspotify on upgrade, clean up old overrides"
```

---

### Task 8: Full end-to-end test

**No files to modify — verification only.**

**Step 1: Deploy to Pi**

```bash
ssh nbrown@<PI_IP> "cd ~/flockify && git pull && sudo systemctl restart go-librespot flockify"
```

**Step 2: Test playback**

```bash
# Local API health
curl -s http://127.0.0.1:3678/status

# Web UI
curl -s http://localhost:5000/api/status

# Switch to Spotify mode via button or API
curl -X POST http://localhost:5000/api/next_mode

# Verify audio is playing
pactl list sink-inputs short
```

**Step 3: Power cycle test (the critical one)**

```bash
sudo reboot
# After reboot, verify:
# 1. go-librespot is running
# 2. Spotify resumes without phone re-pairing
# 3. Web UI is accessible
```

**Step 4: Test button controls**

- Volume up/down
- Next/prev track
- Mode cycling (Spotify → webradio → Spotify)

**Step 5: Final commit**

```bash
git add -A
git commit -m "verified: go-librespot migration complete, power cycle test passed"
```

---

### Task 9: Update README + docs page

**Files:**
- Modify: `README.md`
- Modify: `docs/index.html`

Update references from raspotify/librespot to go-librespot throughout both files. Update the systemd services table, audio architecture section, and troubleshooting.

```bash
git add README.md docs/index.html
git commit -m "docs: update README + intro page for go-librespot"
```
