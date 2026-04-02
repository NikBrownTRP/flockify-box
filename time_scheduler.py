"""
TimeScheduler — Enforces time-based behavior for Flockify Box.

Three periods:
  - Night: display shows sleep screen, all buttons locked, no playback
  - Quiet (wake-up / go-to-bed): lower max volume and dimmer display
  - Day: normal operation
"""

import time
from datetime import datetime
from threading import Thread


class TimeScheduler:
    def __init__(self, config_manager, state_machine, display_manager):
        self.config = config_manager
        self.state_machine = state_machine
        self.display = display_manager
        self._running = False
        self._thread = None
        self._current_period = None

    def _get_schedule(self):
        """Return schedule config dict, or None if disabled."""
        schedule = self.config.get('schedule', {})
        if not schedule.get('enabled', False):
            return None
        return schedule

    def _parse_time(self, time_str):
        """Parse 'HH:MM' string into (hour, minute) tuple."""
        parts = time_str.split(':')
        return int(parts[0]), int(parts[1])

    def _time_in_range(self, now_minutes, start_str, end_str):
        """Check if now_minutes is in [start, end) range, handling midnight wrap."""
        start_h, start_m = self._parse_time(start_str)
        end_h, end_m = self._parse_time(end_str)
        start = start_h * 60 + start_m
        end = end_h * 60 + end_m

        if start <= end:
            return start <= now_minutes < end
        else:
            # Wraps midnight (e.g. 20:00 - 06:00)
            return now_minutes >= start or now_minutes < end

    def get_current_period(self):
        """Return 'night', 'quiet', or 'day' based on current time."""
        schedule = self._get_schedule()
        if not schedule:
            return 'day'

        now = datetime.now()
        now_minutes = now.hour * 60 + now.minute

        # Check nighttime first
        night_start = schedule.get('night_start', '20:00')
        night_end = schedule.get('night_end', '06:00')
        if self._time_in_range(now_minutes, night_start, night_end):
            return 'night'

        # Check wake-up period
        wakeup_start = schedule.get('wakeup_start', '06:00')
        wakeup_end = schedule.get('wakeup_end', '07:00')
        if self._time_in_range(now_minutes, wakeup_start, wakeup_end):
            return 'quiet'

        # Check bedtime period
        bedtime_start = schedule.get('bedtime_start', '19:00')
        bedtime_end = schedule.get('bedtime_end', '20:00')
        if self._time_in_range(now_minutes, bedtime_start, bedtime_end):
            return 'quiet'

        return 'day'

    def get_effective_max_volume(self):
        """Return the max volume for the current period."""
        period = self.get_current_period()
        if period == 'night':
            return 0
        elif period == 'quiet':
            schedule = self._get_schedule()
            if schedule:
                return schedule.get('quiet_max_volume', 40)
        return self.config.get('max_volume', 80)

    def get_effective_backlight(self):
        """Return the backlight level for the current period."""
        period = self.get_current_period()
        if period == 'night':
            schedule = self._get_schedule()
            if schedule:
                return schedule.get('night_backlight', 5)
            return 5
        elif period == 'quiet':
            schedule = self._get_schedule()
            if schedule:
                return schedule.get('quiet_backlight', 40)
        return self.config.get('display', {}).get('backlight', 80)

    def is_locked(self):
        """True during nighttime — all buttons should be ignored."""
        return self.get_current_period() == 'night'

    def start(self):
        """Start the background period-check thread."""
        self._running = True
        self._current_period = self.get_current_period()
        self._apply_period(self._current_period)
        self._thread = Thread(target=self._run, daemon=True)
        self._thread.start()
        print(f"[scheduler] Started — current period: {self._current_period}")

    def stop(self):
        """Stop the background thread."""
        self._running = False

    def _run(self):
        """Check period every 30 seconds."""
        while self._running:
            time.sleep(30)
            self._check_period()

    def _check_period(self):
        """Detect period transitions and apply changes."""
        new_period = self.get_current_period()
        if new_period != self._current_period:
            old = self._current_period
            self._current_period = new_period
            print(f"[scheduler] Period changed: {old} -> {new_period}")
            self._apply_period(new_period)

    def _apply_period(self, period):
        """Apply display/audio settings for the given period."""
        try:
            if period == 'night':
                # Stop all playback
                try:
                    self.state_machine.spotify.pause()
                except Exception:
                    pass
                try:
                    self.state_machine.webradio.stop()
                except Exception:
                    pass
                # Show sleep screen
                self.display.show_sleep_screen()
                self.display.set_backlight(self.get_effective_backlight())

            elif period == 'quiet':
                # Apply quiet backlight
                self.display.set_backlight(self.get_effective_backlight())
                # Cap volume if currently above quiet max
                quiet_max = self.get_effective_max_volume()
                if self.state_machine.volume > quiet_max:
                    self.state_machine.set_volume(quiet_max)

            elif period == 'day':
                # Restore normal backlight
                self.display.set_backlight(self.get_effective_backlight())
                # Re-display the current mode's image
                try:
                    with self.state_machine.lock:
                        self.state_machine._activate_mode()
                except Exception:
                    pass
        except Exception as e:
            print(f"[scheduler] Error applying period {period}: {e}")
