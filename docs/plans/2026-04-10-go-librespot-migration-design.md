# go-librespot Migration Design

**Date**: 2026-04-10
**Status**: Approved
**Problem**: Spotify playback breaks after every power cycle — requires manual re-pairing from the phone app. Root cause: the Spotify Web API (spotipy) is used to control a local librespot device, but the Connect session becomes stale across reboots, producing 502/429 errors. No amount of retry/self-heal logic can fix this because the fundamental architecture routes playback commands through Spotify's cloud.
**Solution**: Replace raspotify (librespot) + spotipy (Web API) with go-librespot, which has a local HTTP API for all playback control. Cloud round-trip eliminated for play/pause/skip/volume.

## Architecture Change

### Before (fragile)

```
Button press
  → state_machine
    → spotify_manager.play_playlist()
      → spotipy.start_playback(device_id, uri)
        → HTTPS to api.spotify.com
          → Spotify Cloud routes to librespot via Connect protocol
            → librespot plays audio
```

Failure points: DNS, OAuth token refresh, Connect session state, rate limiting, device registration race at boot.

### After (robust)

```
Button press
  → state_machine
    → spotify_manager.play_playlist()
      → HTTP POST localhost:3678/player/play {uri}
        → go-librespot plays audio
```

Single failure point: is go-librespot running? (systemd ensures yes)

## go-librespot Setup

### Binary
ARM64 binary from [GitHub releases](https://github.com/devgianlu/go-librespot/releases/latest). Installed to `/usr/local/bin/go-librespot`.

### Configuration (`/etc/go-librespot/config.yml`)

```yaml
device_name: flockifybox
device_type: speaker

# Zeroconf for first-time phone pairing + credential persistence
zeroconf_enabled: true
credentials:
  type: zeroconf
  persist_credentials: true

# Audio
audio_backend: alsa
audio_device: default
bitrate: 320
normalisation_disabled: false
normalisation_pregain: -3

# Volume
volume_steps: 100
initial_volume: 100

# Local API server — replaces Spotify Web API for all playback control
server:
  enabled: true
  address: 127.0.0.1
  port: 3678
```

### Systemd Service (`/etc/systemd/system/go-librespot.service`)

```ini
[Unit]
Description=go-librespot (Spotify Connect)
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=nbrown
ExecStartPre=/bin/sleep 5
ExecStart=/usr/local/bin/go-librespot -config_dir /etc/go-librespot
Restart=on-failure
RestartSec=10
Environment=XDG_RUNTIME_DIR=/run/user/1000

[Install]
WantedBy=multi-user.target
```

## Code Changes

### `spotify_manager.py` — Major Rewrite

Replace all spotipy playback methods with local HTTP calls:

```python
import requests

GO_LIBRESPOT_URL = "http://127.0.0.1:3678"

def play_playlist(self, uri):
    """Start playlist via go-librespot local API."""
    try:
        r = requests.post(f"{GO_LIBRESPOT_URL}/player/play",
                          json={"uri": uri}, timeout=5)
        return r.status_code == 200
    except requests.ConnectionError:
        return False

def next_track(self):
    requests.post(f"{GO_LIBRESPOT_URL}/player/next", timeout=5)

def pause(self):
    requests.post(f"{GO_LIBRESPOT_URL}/player/pause", timeout=5)

def resume(self):
    requests.post(f"{GO_LIBRESPOT_URL}/player/resume", timeout=5)

def set_volume(self, level):
    requests.post(f"{GO_LIBRESPOT_URL}/player/volume",
                  json={"volume": level}, timeout=5)

def get_current_track(self):
    r = requests.get(f"{GO_LIBRESPOT_URL}/status", timeout=5)
    # Parse go-librespot status into our track dict format
```

**Keep spotipy for read-only metadata** (never fails):
- `get_playlist_info(uri)` — name, cover art, track count
- `is_configured()` / `has_credentials()` — check if OAuth creds exist
- OAuth flow in web UI (Settings → Connect Spotify)

**Delete entirely:**
- `find_device()` / `_recover_raspotify()` / `reset_pairing()`
- `_rate_limited()` / `_note_rate_limit()` / `_note_stuck_failure()`
- `_in_boot_grace()` / `_RATE_LIMIT_BACKOFF_SEC` / `_ESCALATION_*`
- All sudoers entries for raspotify restart/credential wipe
- `on_pairing_required` callback / `_waiting_for_pairing` flag

### `state_machine.py` — Simplify

- Remove `boot_resume` flag from `_activate_mode()`
- Remove Spotify sink-input boost thread
- Remove `spotify.set_volume(100)` pinning (go-librespot handles its own volume)
- `_apply_volume()` stays unchanged (PipeWire sink volume = single gain stage)

### `flockify.py` — Simplify

- Remove `on_pairing_required` callback wiring
- Remove `_shutdown_done` raspotify-specific comments
- Boot resume: just call `_activate_mode()` with normal retries (local API is fast)

### `scripts/install.sh` — Replace raspotify with go-librespot

- Download ARM64 binary to `/usr/local/bin/go-librespot`
- Create `/etc/go-librespot/config.yml`
- Install systemd service
- Remove raspotify installation steps
- Remove raspotify override, sudoers entries

### Files to Delete

- `systemd/raspotify-override.conf`
- `systemd/flockify-raspotify.sudoers`
- `scripts/spotify-oauth.sh` (go-librespot handles auth via zeroconf)

## What Stays the Same

- Web UI Settings → Spotify Connection (client_id/secret for metadata API)
- Playlist management (add/remove via spotipy read API)
- Display (cover art fetched via spotipy → cached locally)
- Audio routing (PipeWire, BT/wired switching)
- Volume architecture (single PipeWire sink gain stage)
- Time schedule, idle dimmer, boot splash, WiFi AP

## Migration Path

1. Install go-librespot binary on Pi
2. Create config.yml
3. Test standalone: start go-librespot, pair from phone, verify local API
4. Rewrite spotify_manager.py
5. Simplify state_machine.py / flockify.py
6. Update install.sh
7. Remove raspotify + old files
8. Full end-to-end test (boot, play, power cycle, play again without re-pair)

## Loudness Bump (Separate Change)

Increase `max_output_percent` from 60 to 72 (20% increase):
- `state_machine.py` default value change
- Affects both Spotify and webradio equally (single sink gain stage)
