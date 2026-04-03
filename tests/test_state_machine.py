"""Tests for StateMachine — mode switching, volume control, track navigation."""

import sys
import os
import threading

import pytest
from unittest.mock import MagicMock, patch

# Ensure the project root is on the path so we can import state_machine
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from state_machine import StateMachine


PLAYLISTS = [
    {'name': 'P1', 'uri': 'spotify:playlist:1', 'cover_url': '', 'cover_cached': ''},
    {'name': 'P2', 'uri': 'spotify:playlist:2', 'cover_url': '', 'cover_cached': ''},
]
WEBRADIO_CFG = {'name': 'Radio', 'url': 'http://stream', 'image_path': 'img.png'}


def _make_config_mock():
    """Build a config_manager mock with sensible defaults."""
    config = MagicMock()

    def _get_side_effect(key, default=None):
        mapping = {
            'playlists': PLAYLISTS,
            'webradio': WEBRADIO_CFG,
            'max_volume': 80,
            'volume_step': 5,
        }
        return mapping.get(key, default)

    config.get.side_effect = _get_side_effect
    config.get_state.return_value = {'mode_index': 0, 'volume': 50}
    config.save_state = MagicMock()
    return config


@pytest.fixture
def state_machine():
    config = _make_config_mock()
    spotify = MagicMock()
    webradio = MagicMock()
    display = MagicMock()
    audio_router = MagicMock()
    audio_router.current_output = 'wired'

    sm = StateMachine(config, spotify, webradio, display, audio_router)
    return sm


# -----------------------------------------------------------------
# Mode queries
# -----------------------------------------------------------------

def test_get_mode_count(state_machine):
    # 2 playlists + 1 webradio
    assert state_machine.get_mode_count() == 3


def test_is_spotify_mode_at_zero(state_machine):
    assert state_machine.mode_index == 0
    assert state_machine.is_spotify_mode() is True


def test_is_webradio_mode(state_machine):
    state_machine.mode_index = len(PLAYLISTS)  # index 2
    assert state_machine.is_webradio_mode() is True


def test_get_current_playlist(state_machine):
    playlist = state_machine.get_current_playlist()
    assert playlist is not None
    assert playlist['name'] == 'P1'
    assert playlist['uri'] == 'spotify:playlist:1'


def test_get_current_playlist_webradio_returns_none(state_machine):
    state_machine.mode_index = len(PLAYLISTS)
    assert state_machine.get_current_playlist() is None


# -----------------------------------------------------------------
# Mode switching
# -----------------------------------------------------------------

def test_next_mode_wraps(state_machine):
    assert state_machine.mode_index == 0
    state_machine.next_mode()
    assert state_machine.mode_index == 1
    state_machine.next_mode()
    assert state_machine.mode_index == 2
    state_machine.next_mode()
    assert state_machine.mode_index == 0  # wrapped


def test_set_mode_valid(state_machine):
    state_machine.set_mode(1)
    assert state_machine.mode_index == 1


def test_set_mode_invalid(state_machine):
    original = state_machine.mode_index
    state_machine.set_mode(99)
    assert state_machine.mode_index == original


# -----------------------------------------------------------------
# Volume
# -----------------------------------------------------------------

def test_volume_up(state_machine):
    assert state_machine.volume == 50
    state_machine.volume_up()
    assert state_machine.volume == 55


def test_volume_up_respects_max(state_machine):
    state_machine.volume = 78
    state_machine.volume_up()
    assert state_machine.volume == 80  # capped at max_volume


def test_volume_down(state_machine):
    assert state_machine.volume == 50
    state_machine.volume_down()
    assert state_machine.volume == 45


def test_volume_down_floor(state_machine):
    state_machine.volume = 3
    state_machine.volume_down()
    assert state_machine.volume == 0  # not negative


def test_set_volume_clamps(state_machine):
    state_machine.set_volume(999)
    assert state_machine.volume == 80  # clamped to max_volume


# -----------------------------------------------------------------
# Track navigation
# -----------------------------------------------------------------

def test_next_track_spotify_mode(state_machine):
    assert state_machine.is_spotify_mode()
    state_machine.next_track()
    state_machine.spotify.next_track.assert_called_once()


def test_next_track_webradio_noop(state_machine):
    state_machine.mode_index = len(PLAYLISTS)  # webradio
    state_machine.next_track()
    state_machine.spotify.next_track.assert_not_called()


# -----------------------------------------------------------------
# Locked (night-time) behaviour
# -----------------------------------------------------------------

def test_locked_actions_noop(state_machine):
    scheduler = MagicMock()
    scheduler.is_locked.return_value = True
    state_machine.time_scheduler = scheduler

    original_mode = state_machine.mode_index
    original_volume = state_machine.volume

    state_machine.next_mode()
    state_machine.volume_up()
    state_machine.next_track()

    assert state_machine.mode_index == original_mode
    assert state_machine.volume == original_volume
    state_machine.spotify.next_track.assert_not_called()


# -----------------------------------------------------------------
# Status
# -----------------------------------------------------------------

def test_get_status_structure(state_machine):
    # Provide a time_scheduler so get_status can call get_current_period
    scheduler = MagicMock()
    scheduler.get_current_period.return_value = 'day'
    scheduler.get_effective_max_volume.return_value = 80
    state_machine.time_scheduler = scheduler

    status = state_machine.get_status()

    required_keys = {
        'mode', 'mode_index', 'total_modes', 'volume',
        'max_volume', 'audio_output', 'is_playing', 'period',
    }
    assert required_keys.issubset(status.keys())
