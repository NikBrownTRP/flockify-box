"""
StateMachine — Central coordinator for Flockify Box.

Manages mode switching (Spotify playlists / webradio), volume control,
and track navigation.  Called by ButtonController, Flask web API, and
AudioRouter callback.
"""

import threading


class StateMachine:
    def __init__(self, config_manager, spotify_manager, webradio_player,
                 display_manager, audio_router):
        self.config = config_manager
        self.spotify = spotify_manager
        self.webradio = webradio_player
        self.display = display_manager
        self.audio_router = audio_router
        self.lock = threading.RLock()
        self.time_scheduler = None  # Set by flockify.py after init
        self.idle_dimmer = None  # Set by flockify.py after init
        # Set to True by flockify.py on startup when a clean-shutdown flag file is found
        # (written by _monitor_power_button before calling systemctl poweroff).
        # Read/written outside self.lock — safe in CPython due to the GIL; single bool assignment
        # is atomic. Cleared and playback triggered by the first _notify_activity call.
        self.silent_mode = False

        # Load persisted state
        state = self.config.get_state()
        self.volume = state.get('volume', 50)
        self.mode_index = state.get('mode_index', 0)

        # Clamp mode_index to valid range
        if self.mode_index < 0 or self.mode_index >= self.get_mode_count():
            self.mode_index = self._webradio_index()

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _playlists(self):
        """Return the playlists list from config (may be empty)."""
        return self.config.get('playlists', [])

    def _webradio_index(self):
        """The mode_index value that represents webradio."""
        return len(self._playlists())

    # ------------------------------------------------------------------
    # Mode queries
    # ------------------------------------------------------------------

    def get_mode_count(self):
        """Total number of modes: one per playlist + 1 webradio."""
        return len(self._playlists()) + 1

    def is_webradio_mode(self):
        return self.mode_index == self._webradio_index()

    def is_spotify_mode(self):
        return self.mode_index < self._webradio_index()

    def get_current_playlist(self):
        """Return the playlist dict for the current mode, or None if webradio."""
        if self.is_spotify_mode():
            playlists = self._playlists()
            if 0 <= self.mode_index < len(playlists):
                return playlists[self.mode_index]
        return None

    # ------------------------------------------------------------------
    # Mode switching
    # ------------------------------------------------------------------

    def _is_locked(self):
        """Check if time scheduler has locked all controls (nighttime)."""
        return self.time_scheduler and self.time_scheduler.is_locked()

    def _effective_max_volume(self):
        """Return max volume respecting time schedule."""
        if self.time_scheduler:
            return self.time_scheduler.get_effective_max_volume()
        return self.config.get('max_volume', 80)

    def _is_mode_allowed(self):
        """Check if current mode is allowed in the current time period."""
        if self.is_webradio_mode():
            return True  # webradio always allowed
        playlist = self.get_current_playlist()
        if not playlist:
            return True
        current_period = 'day'
        if self.time_scheduler:
            current_period = self.time_scheduler.get_current_period()
        allowed = playlist.get('allowed_periods', ['day', 'quiet'])
        return current_period in allowed

    def next_mode(self):
        if self._is_locked():
            return
        with self.lock:
            count = self.get_mode_count()
            for _ in range(count):
                self.mode_index = (self.mode_index + 1) % count
                if self._is_mode_allowed():
                    break
            self._activate_mode()
            self._save_state()
        self._notify_activity()

    def prev_mode(self):
        """Cycle backward through modes, skipping disallowed ones."""
        if self._is_locked():
            return
        with self.lock:
            count = self.get_mode_count()
            for _ in range(count):
                self.mode_index = (self.mode_index - 1) % count
                if self._is_mode_allowed():
                    break
            self._activate_mode()
            self._save_state()
        self._notify_activity()

    def set_mode(self, index):
        if self._is_locked():
            return
        with self.lock:
            if 0 <= index < self.get_mode_count():
                self.mode_index = index
                self._activate_mode()
                self._save_state()
        self._notify_activity()

    # ------------------------------------------------------------------
    # Volume
    # ------------------------------------------------------------------

    def _show_volume_overlay(self):
        """Trigger the SPI display volume overlay (no-op if no display)."""
        try:
            self.display.show_volume_overlay(self.volume, self._effective_max_volume())
        except Exception as e:
            print(f"[StateMachine] Error showing volume overlay: {e}")

    def _notify_activity(self):
        """Tell the idle dimmer that the user just interacted with the box.

        If the box booted in silent mode (after a clean J2 shutdown), the
        first user interaction clears silent mode and starts playback.
        """
        if self.silent_mode:
            self.silent_mode = False
            try:
                with self.lock:
                    self._activate_mode()
            except Exception as e:
                print(f"[StateMachine] Error activating from silent mode: {e}")
        if self.idle_dimmer is not None:
            try:
                self.idle_dimmer.notify_activity()
            except Exception as e:
                print(f"[StateMachine] Error notifying idle dimmer: {e}")

    def volume_up(self):
        if self._is_locked():
            return
        with self.lock:
            step = self.config.get('volume_step', 5)
            max_vol = self._effective_max_volume()
            self.volume = min(self.volume + step, max_vol)
            self._apply_volume(self.volume)
            self._save_state()
        # Render overlay FIRST (slow SPI write happens while display may
        # still be dimmed), THEN wake the backlight. The user sees the
        # bright overlay appear in one snap instead of: bright cover →
        # delay → bright overlay.
        self._show_volume_overlay()
        self._notify_activity()

    def volume_down(self):
        if self._is_locked():
            return
        with self.lock:
            step = self.config.get('volume_step', 5)
            self.volume = max(self.volume - step, 0)
            self._apply_volume(self.volume)
            self._save_state()
        self._show_volume_overlay()
        self._notify_activity()

    def set_volume(self, level):
        if self._is_locked():
            return
        with self.lock:
            max_vol = self._effective_max_volume()
            self.volume = max(0, min(int(level), max_vol))
            self._apply_volume(self.volume)
            self._save_state()
        self._show_volume_overlay()
        self._notify_activity()

    # ------------------------------------------------------------------
    # Track navigation
    # ------------------------------------------------------------------

    def next_track(self):
        if self._is_locked():
            return
        with self.lock:
            if self.is_spotify_mode():
                try:
                    self.spotify.next_track()
                except Exception as e:
                    print(f"[StateMachine] Error skipping track: {e}")
        self._notify_activity()

    def prev_track(self):
        if self._is_locked():
            return
        with self.lock:
            if self.is_spotify_mode():
                try:
                    self.spotify.previous_track()
                except Exception as e:
                    print(f"[StateMachine] Error going to previous track: {e}")
        self._notify_activity()

    def prev_track_hard(self):
        """Force-go to the actual previous track.

        go-librespot's /player/prev rewinds to 0 if position > 3 s,
        and only goes to the previous track if position is already near
        0. Calling it twice (100 ms apart) guarantees we go back a full
        track regardless of current playback position.
        """
        if self._is_locked():
            return
        with self.lock:
            if self.is_spotify_mode():
                try:
                    self.spotify.previous_track()
                    import time as _t
                    _t.sleep(0.1)
                    self.spotify.previous_track()
                except Exception as e:
                    print(f"[StateMachine] Error going to previous track (hard): {e}")
        self._notify_activity()

    def play_pause(self):
        """Toggle playback pause/resume on the current player."""
        if self._is_locked():
            return
        with self.lock:
            if self.is_spotify_mode():
                try:
                    self.spotify.play_pause()
                except Exception as e:
                    print(f"[StateMachine] Error toggling play/pause: {e}")
            # Webradio: mpv has pause/resume but the current architecture
            # doesn't expose it; pressing play/pause while on webradio
            # is a no-op for now.
        self._notify_activity()

    # ------------------------------------------------------------------
    # Status
    # ------------------------------------------------------------------

    def get_status(self):
        # Snapshot state under lock (fast), then do Spotify HTTP call outside lock
        with self.lock:
            webradio_cfg = self.config.get('webradio', {})
            max_vol = self.config.get('max_volume', 80)
            is_webradio = self.is_webradio_mode()
            is_spotify = self.is_spotify_mode()
            playlist = self.get_current_playlist()
            mode_index = self.mode_index
            volume = self.volume
            total_modes = self.get_mode_count()

        period = self.time_scheduler.get_current_period() if self.time_scheduler else 'day'

        status = {
            'mode': 'webradio' if is_webradio else 'spotify',
            'mode_index': mode_index,
            'total_modes': total_modes,
            'volume': volume,
            'max_volume': self._effective_max_volume(),
            'audio_output': self.audio_router.current_output,
            'is_playing': True,
            'period': period,
        }

        if is_webradio:
            status['playlist_name'] = webradio_cfg.get('name', 'Web Radio')
        else:
            status['playlist_name'] = playlist.get('name', '') if playlist else ''
            # Spotify API call outside lock to avoid blocking buttons
            try:
                track_info = self.spotify.get_current_track()
                if track_info:
                    status['track'] = track_info
                    status['is_playing'] = track_info.get('is_playing', True)
            except Exception as e:
                print(f"[StateMachine] Error getting track info: {e}")

        return status

    # ------------------------------------------------------------------
    # Internal methods
    # ------------------------------------------------------------------

    def _activate_mode(self):
        """Core transition logic. Must be called while self.lock is held."""
        if self.silent_mode:
            # Box booted silently after a clean shutdown — don't start playback.
            # First user action (via _notify_activity) will clear this and activate.
            return
        if not self._is_mode_allowed():
            # Current mode not allowed in this period, switch to webradio
            self.mode_index = self._webradio_index()
        try:
            if self.is_spotify_mode():
                playlist = self.get_current_playlist()
                if not playlist:
                    return
                # Stop webradio if it was playing
                try:
                    self.webradio.stop()
                except Exception:
                    pass
                # Start Spotify playlist
                try:
                    self.spotify.play_playlist(playlist.get('uri', ''))
                except Exception as e:
                    print(f"[StateMachine] Error starting Spotify playlist: {e}")
                self._apply_volume(self.volume)
                # Update display
                try:
                    self.display.show_playlist_cover(playlist)
                except Exception as e:
                    print(f"[StateMachine] Error showing playlist cover: {e}")
            else:
                # Webradio mode
                webradio_cfg = self.config.get('webradio', {})
                # Pause Spotify
                try:
                    self.spotify.pause()
                except Exception:
                    pass
                # Start webradio — use play_station() directly;
                # audio_router handles sink routing, not webradio_player
                try:
                    url = webradio_cfg.get('url', '')
                    self.webradio.play_station(url)
                    # Webradio streams are broadcast-hot (~-4 dBFS RMS
                    # measured) vs Spotify's normalised ~-17 dBFS. Drop
                    # mpv to 25% (-12 dB) to close the 13 dB gap.
                    # Tunable via `webradio_volume` in config.
                    wr_vol = int(self.config.get('webradio_volume', 25))
                    self.webradio.set_volume(wr_vol)
                    self._apply_volume(self.volume)
                except Exception as e:
                    print(f"[StateMachine] Error starting webradio: {e}")
                # Update display
                try:
                    image_path = webradio_cfg.get('image_path', '')
                    if image_path:
                        self.display.show_webradio_image(image_path)
                except Exception as e:
                    print(f"[StateMachine] Error showing webradio image: {e}")
        except Exception as e:
            print(f"[StateMachine] Error activating mode: {e}")

    def _apply_volume(self, volume):
        """Set the PipeWire default-sink volume.

        Single gain stage architecture: both librespot and mpv run at
        unity (internal volume 100%). The user's knob controls the
        PipeWire sink volume directly — this is the last stage before
        the DAC, keeping the full signal amplitude through the entire
        digital path and avoiding the quantisation-noise / quality
        degradation that came from stacking three attenuation layers.

        `max_output_percent` (default 60) caps the sink volume so
        knob=100 maps to a kid-safe ceiling.
        """
        ceiling = int(self.config.get('max_output_percent', 72))
        scaled = max(0, min(100, int(round(volume * ceiling / 100))))
        try:
            import subprocess
            subprocess.run(
                ["pactl", "set-sink-volume", "@DEFAULT_SINK@", f"{scaled}%"],
                check=False,
                capture_output=True,
                timeout=3,
            )
        except Exception as e:
            print(f"[StateMachine] Error applying volume: {e}")

    def _save_state(self):
        """Persist mode_index and volume to config."""
        try:
            self.config.save_state(self.mode_index, self.volume)
        except Exception as e:
            print(f"[StateMachine] Error saving state: {e}")

    # ------------------------------------------------------------------
    # Callbacks
    # ------------------------------------------------------------------

    def on_audio_output_changed(self, output_type):
        """Called by AudioRouter when audio output switches."""
        try:
            self.display.set_bluetooth_active(output_type == "bluetooth")
        except Exception as e:
            print(f"[StateMachine] Error updating bluetooth display: {e}")
