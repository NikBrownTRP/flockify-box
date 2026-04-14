# Long-Press Buttons + Dashboard Playback Controls + Quiet Auto-Skip

**Date**: 2026-04-14
**Status**: Approved

## Problem

Three related items:

1. **Bug**: When quiet period starts while a restricted playlist is already playing, the scheduler only caps the volume — the restricted playlist keeps playing through bedtime/wakeup. Same issue after boot into quiet.
2. **Feature: long-press buttons**: A way to cycle BACKWARD through playlists, and a way to skip to the actual previous track (not just rewind the current one).
3. **Feature: dashboard controls**: Pause, next track, previous track buttons on the web UI dashboard for parent-side control.

## Design

### 1. Quiet auto-skip bug fix

`time_scheduler._apply_period('quiet')` will call `state_machine.next_mode()` if the current mode is not allowed in quiet. `next_mode()` already skips disallowed modes and falls back to webradio. Same fix in `flockify.py` boot-resume path.

### 2. Long-press button handlers

Button controller adds a 700 ms timer on press. If released before 700 ms → short-press action. If still held at 700 ms → long-press action, short-press cancelled.

- **Next Mode (GPIO 12)**: short = `next_mode()`, long = `prev_mode()` (new — cycles backward, same skip logic)
- **Prev Track (GPIO 26)**: short = `prev_track()` (rewinds current), long = real previous track (`prev_track()` twice with 100 ms delay: first rewinds, second actually goes back a track)

### 3. Dashboard playback controls

Three icon buttons added to `index.html` — ⏯ Play/Pause, ⏮ Previous, ⏭ Next — calling three new endpoints: `POST /api/play_pause`, `POST /api/prev_track`, `POST /api/next_track`. Handlers delegate to existing `state_machine` methods; `play_pause` is new (calls `spotify.play_pause()` via go-librespot `/player/playpause`).

## Files

- `time_scheduler.py` — auto-skip in `_apply_period('quiet')`
- `state_machine.py` — `prev_mode()`, `play_pause()` methods
- `spotify_manager.py` — `play_pause()` method hitting `/player/playpause`
- `button_controller.py` — long-press timer + callbacks
- `web/app.py` — three new API endpoints
- `web/templates/index.html` — three buttons
- `web/static/js/app.js` — click handlers
- `tests/` — tests for `prev_mode`, quiet auto-skip, long-press state machine
