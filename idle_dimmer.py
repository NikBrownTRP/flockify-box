"""
IdleDimmer — drops the SPI display backlight to a low level after a period
of no user interaction, and instantly restores it on the next button press
or web UI action.

Only active during the 'day' period of the time schedule. The schedule
already manages backlight during quiet/night periods, so we step out of
the way for those.

Usage:
    dimmer = IdleDimmer(display_manager, time_scheduler, config_manager)
    dimmer.start()
    # On any user-driven activity:
    dimmer.notify_activity()
    # On shutdown:
    dimmer.stop()
"""

import threading
import time

IDLE_TIMEOUT_SEC = 60          # how long to wait before dimming
IDLE_DIM_BACKLIGHT = 20        # backlight level when dimmed (0..100)
POLL_INTERVAL_SEC = 5          # how often the background thread checks


class IdleDimmer:
    def __init__(self, display_manager, time_scheduler, config_manager):
        self.display = display_manager
        self.scheduler = time_scheduler
        self.config = config_manager

        self._lock = threading.Lock()
        self._last_activity = time.monotonic()
        self._dimmed = False
        self._running = False
        self._thread = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def notify_activity(self):
        """Mark the box as recently used. If currently dimmed, restore
        the day-time backlight immediately."""
        with self._lock:
            self._last_activity = time.monotonic()
            was_dimmed = self._dimmed
            self._dimmed = False
        if was_dimmed:
            try:
                self.display.set_backlight(self._day_backlight())
            except Exception as e:
                print(f"[IdleDimmer] Error restoring backlight: {e}")

    def start(self):
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        print(f"[IdleDimmer] Started — idle timeout {IDLE_TIMEOUT_SEC}s, dim level {IDLE_DIM_BACKLIGHT}%")

    def stop(self):
        self._running = False
        if self._thread is not None:
            self._thread.join(timeout=POLL_INTERVAL_SEC + 1)
            self._thread = None

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _day_backlight(self):
        """Return the configured day-time display backlight level."""
        return self.config.get("display", {}).get("backlight", 80)

    def _current_period(self):
        """Return 'day' / 'quiet' / 'night' from the time scheduler."""
        if self.scheduler is None:
            return "day"
        try:
            return self.scheduler.get_current_period()
        except Exception:
            return "day"

    def _run(self):
        """Background thread: poll periodically and dim if idle."""
        while self._running:
            time.sleep(POLL_INTERVAL_SEC)
            if not self._running:
                break
            try:
                self._maybe_dim()
            except Exception as e:
                print(f"[IdleDimmer] Error in poll: {e}")

    def _maybe_dim(self):
        # Only manage the backlight in 'day' mode. quiet/night are handled
        # by the time scheduler so we don't fight it.
        if self._current_period() != "day":
            with self._lock:
                # Reset timer so we don't immediately dim after returning to day
                self._last_activity = time.monotonic()
                self._dimmed = False
            return

        with self._lock:
            if self._dimmed:
                return  # already dimmed
            elapsed = time.monotonic() - self._last_activity
            if elapsed < IDLE_TIMEOUT_SEC:
                return
            # Time to dim
            self._dimmed = True

        try:
            self.display.set_backlight(IDLE_DIM_BACKLIGHT)
            print(f"[IdleDimmer] Dimmed display to {IDLE_DIM_BACKLIGHT}% after {IDLE_TIMEOUT_SEC}s idle")
        except Exception as e:
            print(f"[IdleDimmer] Error dimming backlight: {e}")
