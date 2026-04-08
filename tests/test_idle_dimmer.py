"""Tests for IdleDimmer."""

from unittest.mock import MagicMock
import idle_dimmer
from idle_dimmer import IdleDimmer


def _make_dimmer(period="day", day_backlight=80):
    display = MagicMock()
    scheduler = MagicMock()
    scheduler.get_current_period.return_value = period
    config = MagicMock()
    config.get.return_value = {"backlight": day_backlight}
    return IdleDimmer(display, scheduler, config), display, scheduler, config


def test_dim_after_idle_timeout(monkeypatch):
    """After IDLE_TIMEOUT_SEC, _maybe_dim() lowers backlight."""
    dimmer, display, _, _ = _make_dimmer()
    # Pretend the last activity was a long time ago by mutating the timestamp
    dimmer._last_activity -= idle_dimmer.IDLE_TIMEOUT_SEC + 5
    dimmer._maybe_dim()
    display.set_backlight.assert_called_once_with(idle_dimmer.IDLE_DIM_BACKLIGHT)
    assert dimmer._dimmed is True


def test_does_not_dim_within_timeout():
    """If activity was recent, _maybe_dim() does nothing."""
    dimmer, display, _, _ = _make_dimmer()
    # Last activity is "now" (just constructed)
    dimmer._maybe_dim()
    display.set_backlight.assert_not_called()
    assert dimmer._dimmed is False


def test_notify_activity_restores_backlight():
    """notify_activity() while dimmed restores the day backlight."""
    dimmer, display, _, _ = _make_dimmer(day_backlight=80)
    dimmer._dimmed = True  # pretend we're dimmed
    dimmer.notify_activity()
    display.set_backlight.assert_called_once_with(80)
    assert dimmer._dimmed is False


def test_notify_activity_when_not_dimmed_does_nothing():
    """notify_activity() while not dimmed only updates the timestamp."""
    dimmer, display, _, _ = _make_dimmer()
    dimmer.notify_activity()
    display.set_backlight.assert_not_called()


def test_does_not_dim_during_quiet_period():
    """During quiet/night periods the dimmer steps aside."""
    dimmer, display, _, _ = _make_dimmer(period="quiet")
    dimmer._last_activity -= idle_dimmer.IDLE_TIMEOUT_SEC + 5
    dimmer._maybe_dim()
    display.set_backlight.assert_not_called()
    assert dimmer._dimmed is False


def test_does_not_dim_during_night():
    dimmer, display, _, _ = _make_dimmer(period="night")
    dimmer._last_activity -= idle_dimmer.IDLE_TIMEOUT_SEC + 5
    dimmer._maybe_dim()
    display.set_backlight.assert_not_called()


def test_dim_is_idempotent():
    """Calling _maybe_dim() while already dimmed doesn't re-set backlight."""
    dimmer, display, _, _ = _make_dimmer()
    dimmer._last_activity -= idle_dimmer.IDLE_TIMEOUT_SEC + 5
    dimmer._maybe_dim()  # first dim
    display.set_backlight.reset_mock()
    dimmer._last_activity -= 100  # still idle
    dimmer._maybe_dim()  # second poll
    display.set_backlight.assert_not_called()


def test_day_backlight_reads_from_config():
    """Day backlight value comes from config['display']['backlight']."""
    dimmer, _, _, config = _make_dimmer(day_backlight=55)
    assert dimmer._day_backlight() == 55


def test_start_stop_safe_to_call_multiple_times():
    """start() and stop() should not crash if called when already in that state."""
    dimmer, _, _, _ = _make_dimmer()
    dimmer.start()
    dimmer.start()  # second start is no-op
    dimmer.stop()
    dimmer.stop()  # second stop is no-op
