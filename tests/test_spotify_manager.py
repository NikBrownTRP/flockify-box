"""Tests for SpotifyManager (spotify_manager.py)."""

import pytest
from unittest.mock import MagicMock, patch, PropertyMock

from spotipy.exceptions import SpotifyException


@pytest.fixture
def empty_config():
    """Config manager with no Spotify credentials."""
    cm = MagicMock()
    cm.get.return_value = {}
    return cm


@pytest.fixture
def full_config():
    """Config manager with all Spotify credentials set."""
    cm = MagicMock()
    cm.get.return_value = {
        "client_id": "test_id",
        "client_secret": "test_secret",
        "refresh_token": "test_token",
        "device_name": "flockifybox",
    }
    return cm


@patch("spotify_manager.spotipy")
def test_is_configured_false(mock_spotipy, empty_config):
    from spotify_manager import SpotifyManager

    mgr = SpotifyManager(empty_config)
    assert mgr.is_configured() is False


@patch("spotify_manager.spotipy")
@patch("spotify_manager.SpotifyOAuth")
def test_is_configured_true(mock_oauth, mock_spotipy, full_config):
    from spotify_manager import SpotifyManager

    mgr = SpotifyManager(full_config)
    assert mgr.is_configured() is True


@patch("spotify_manager.spotipy")
@patch("spotify_manager.SpotifyOAuth")
def test_play_playlist_calls_api(mock_oauth, mock_spotipy, full_config):
    from spotify_manager import SpotifyManager

    mock_sp = MagicMock()
    mock_sp.devices.return_value = {
        "devices": [{"name": "flockifybox", "id": "dev123"}]
    }
    mock_spotipy.Spotify.return_value = mock_sp

    mgr = SpotifyManager(full_config)
    mgr.sp = mock_sp

    result = mgr.play_playlist("spotify:playlist:XYZ")
    mock_sp.start_playback.assert_called_once_with(
        device_id="dev123", context_uri="spotify:playlist:XYZ"
    )
    assert result is True


@patch("spotify_manager.spotipy")
@patch("spotify_manager.SpotifyOAuth")
def test_next_track_calls_api(mock_oauth, mock_spotipy, full_config):
    from spotify_manager import SpotifyManager

    mock_sp = MagicMock()
    mock_sp.devices.return_value = {
        "devices": [{"name": "flockifybox", "id": "dev123"}]
    }
    mock_spotipy.Spotify.return_value = mock_sp

    mgr = SpotifyManager(full_config)
    mgr.sp = mock_sp
    mgr._device_id = "dev123"

    result = mgr.next_track()
    mock_sp.next_track.assert_called_once_with(device_id="dev123")
    assert result is True


@patch("spotify_manager.spotipy")
@patch("spotify_manager.SpotifyOAuth")
def test_get_current_track_returns_dict(mock_oauth, mock_spotipy, full_config):
    from spotify_manager import SpotifyManager

    mock_sp = MagicMock()
    mock_sp.current_playback.return_value = {
        "is_playing": True,
        "item": {
            "name": "Test Song",
            "artists": [{"name": "Artist A"}, {"name": "Artist B"}],
            "album": {
                "name": "Test Album",
                "images": [{"url": "http://img/cover.jpg"}],
            },
        },
    }
    mock_spotipy.Spotify.return_value = mock_sp

    mgr = SpotifyManager(full_config)
    mgr.sp = mock_sp

    track = mgr.get_current_track()
    assert track is not None
    assert track["name"] == "Test Song"
    assert "Artist A" in track["artist"]
    assert track["is_playing"] is True


@patch("spotify_manager.spotipy")
@patch("spotify_manager.SpotifyOAuth")
def test_get_current_track_none(mock_oauth, mock_spotipy, full_config):
    from spotify_manager import SpotifyManager

    mock_sp = MagicMock()
    mock_sp.current_playback.return_value = None
    mock_spotipy.Spotify.return_value = mock_sp

    mgr = SpotifyManager(full_config)
    mgr.sp = mock_sp

    track = mgr.get_current_track()
    assert track is None


@patch("spotify_manager.SpotifyOAuth")
def test_api_error_graceful(mock_oauth, full_config):
    """sp.next_track() raising SpotifyException should be caught gracefully."""
    from spotify_manager import SpotifyManager

    mock_sp = MagicMock()
    mock_sp.next_track.side_effect = SpotifyException(
        http_status=500, code=-1, msg="Server error"
    )
    mock_sp.devices.return_value = {
        "devices": [{"name": "flockifybox", "id": "dev123"}]
    }

    mgr = SpotifyManager(full_config)
    mgr.sp = mock_sp
    mgr._device_id = "dev123"

    # Should not raise; returns False on error
    result = mgr.next_track()
    assert result is False
