"""Tests for TimeScheduler — period detection, volume/backlight limits, locking."""

import sys
import os
import threading
from datetime import datetime

import pytest
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from time_scheduler import TimeScheduler


SCHEDULE_CFG = {
    'enabled': True,
    'night_start': '20:00',
    'night_end': '06:00',
    'wakeup_start': '06:00',
    'wakeup_end': '07:00',
    'bedtime_start': '19:00',
    'bedtime_end': '20:00',
    'quiet_max_volume': 40,
    'quiet_backlight': 40,
    'night_backlight': 5,
}


def _make_config(schedule=None):
    config = MagicMock()
    if schedule is None:
        schedule = dict(SCHEDULE_CFG)

    def _get_side_effect(key, default=None):
        mapping = {
            'schedule': schedule,
            'max_volume': 80,
            'display': {'backlight': 80},
        }
        return mapping.get(key, default)

    config.get.side_effect = _get_side_effect
    return config


def _make_state_machine():
    sm = MagicMock()
    sm.lock = threading.Lock()
    sm.volume = 50
    sm.spotify = MagicMock()
    sm.webradio = MagicMock()
    return sm


@pytest.fixture
def scheduler():
    config = _make_config()
    sm = _make_state_machine()
    display = MagicMock()
    return TimeScheduler(config, sm, display)


@pytest.fixture
def disabled_scheduler():
    config = _make_config(schedule={'enabled': False})
    sm = _make_state_machine()
    display = MagicMock()
    return TimeScheduler(config, sm, display)


# -----------------------------------------------------------------
# _parse_time
# -----------------------------------------------------------------

def test_parse_time(scheduler):
    assert scheduler._parse_time("20:00") == (20, 0)
    assert scheduler._parse_time("06:30") == (6, 30)


# -----------------------------------------------------------------
# _time_in_range
# -----------------------------------------------------------------

def test_time_in_range_normal(scheduler):
    # 600 min = 10:00, range 08:00-20:00 (480-1200)
    assert scheduler._time_in_range(600, "08:00", "20:00") is True


def test_time_in_range_outside(scheduler):
    # 420 min = 07:00, NOT in 08:00-20:00
    assert scheduler._time_in_range(420, "08:00", "20:00") is False


def test_time_in_range_midnight_wrap_late(scheduler):
    # 1380 min = 23:00, in 20:00-06:00 (wraps midnight)
    assert scheduler._time_in_range(1380, "20:00", "06:00") is True


def test_time_in_range_midnight_wrap_early(scheduler):
    # 180 min = 03:00, in 20:00-06:00
    assert scheduler._time_in_range(180, "20:00", "06:00") is True


def test_time_in_range_midnight_wrap_outside(scheduler):
    # 600 min = 10:00, NOT in 20:00-06:00
    assert scheduler._time_in_range(600, "20:00", "06:00") is False


# -----------------------------------------------------------------
# get_current_period (mocked datetime)
# -----------------------------------------------------------------

def _mock_datetime_at(hour, minute=0):
    """Return a mock that replaces datetime.now() with a fixed time."""
    mock_dt = MagicMock()
    mock_dt.now.return_value = datetime(2026, 1, 15, hour, minute, 0)
    # Keep the real class accessible for anything else
    mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
    return mock_dt


@patch('time_scheduler.datetime')
def test_period_night(mock_datetime, scheduler):
    mock_datetime.now.return_value = datetime(2026, 1, 15, 23, 0, 0)
    assert scheduler.get_current_period() == 'night'


@patch('time_scheduler.datetime')
def test_period_quiet_morning(mock_datetime, scheduler):
    mock_datetime.now.return_value = datetime(2026, 1, 15, 6, 30, 0)
    assert scheduler.get_current_period() == 'quiet'


@patch('time_scheduler.datetime')
def test_period_quiet_evening(mock_datetime, scheduler):
    mock_datetime.now.return_value = datetime(2026, 1, 15, 19, 30, 0)
    assert scheduler.get_current_period() == 'quiet'


@patch('time_scheduler.datetime')
def test_period_day(mock_datetime, scheduler):
    mock_datetime.now.return_value = datetime(2026, 1, 15, 12, 0, 0)
    assert scheduler.get_current_period() == 'day'


@patch('time_scheduler.datetime')
def test_period_disabled(mock_datetime, disabled_scheduler):
    mock_datetime.now.return_value = datetime(2026, 1, 15, 23, 0, 0)
    assert disabled_scheduler.get_current_period() == 'day'


# -----------------------------------------------------------------
# get_effective_max_volume
# -----------------------------------------------------------------

@patch('time_scheduler.datetime')
def test_effective_max_volume_night(mock_datetime, scheduler):
    mock_datetime.now.return_value = datetime(2026, 1, 15, 23, 0, 0)
    assert scheduler.get_effective_max_volume() == 0


@patch('time_scheduler.datetime')
def test_effective_max_volume_quiet(mock_datetime, scheduler):
    mock_datetime.now.return_value = datetime(2026, 1, 15, 6, 30, 0)
    assert scheduler.get_effective_max_volume() == 40


@patch('time_scheduler.datetime')
def test_effective_max_volume_day(mock_datetime, scheduler):
    mock_datetime.now.return_value = datetime(2026, 1, 15, 12, 0, 0)
    assert scheduler.get_effective_max_volume() == 80


# -----------------------------------------------------------------
# is_locked
# -----------------------------------------------------------------

@patch('time_scheduler.datetime')
def test_is_locked_night(mock_datetime, scheduler):
    mock_datetime.now.return_value = datetime(2026, 1, 15, 23, 0, 0)
    assert scheduler.is_locked() is True


@patch('time_scheduler.datetime')
def test_is_locked_day(mock_datetime, scheduler):
    mock_datetime.now.return_value = datetime(2026, 1, 15, 12, 0, 0)
    assert scheduler.is_locked() is False
