"""Tests for SpotifyManager (spotify_manager.py)."""

import pytest
from unittest.mock import MagicMock, patch


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


# ── Credential / config tests (unchanged logic) ────────────────


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
def test_has_credentials_true(mock_oauth, mock_spotipy, full_config):
    from spotify_manager import SpotifyManager
    mgr = SpotifyManager(full_config)
    assert mgr.has_credentials() is True


@patch("spotify_manager.spotipy")
def test_has_credentials_false(mock_spotipy, empty_config):
    from spotify_manager import SpotifyManager
    mgr = SpotifyManager(empty_config)
    assert mgr.has_credentials() is False


@patch("spotify_manager.spotipy")
@patch("spotify_manager.SpotifyOAuth")
def test_logout_clears_refresh_token(mock_oauth, mock_spotipy, tmp_path, monkeypatch):
    """logout() should clear refresh_token and token cache but keep client_id/secret."""
    from spotify_manager import SpotifyManager
    import spotify_manager as sm

    cache_file = tmp_path / ".spotify_token_cache"
    cache_file.write_text("dummy-token-data")
    monkeypatch.setattr(sm, "TOKEN_CACHE_PATH", str(cache_file))

    spotify_dict = {
        "client_id": "cid",
        "client_secret": "csec",
        "refresh_token": "rtok",
        "device_name": "flockifybox",
    }
    cm = MagicMock()
    cm.get.return_value = spotify_dict

    def set_side_effect(key, value):
        if key == "spotify":
            spotify_dict.update(value)
    cm.set.side_effect = set_side_effect

    mgr = SpotifyManager(cm)
    mgr.sp = MagicMock()

    mgr.logout()

    assert spotify_dict["refresh_token"] == ""
    assert spotify_dict["client_id"] == "cid"
    assert spotify_dict["client_secret"] == "csec"
    assert not cache_file.exists()
    assert mgr.sp is None


@patch("spotify_manager.spotipy")
@patch("spotify_manager.SpotifyOAuth")
def test_reauth_url_returns_url(mock_oauth, mock_spotipy, full_config):
    from spotify_manager import SpotifyManager
    mock_oauth_instance = MagicMock()
    mock_oauth_instance.get_authorize_url.return_value = "https://accounts.spotify.com/authorize?x=1"
    mock_oauth.return_value = mock_oauth_instance

    mgr = SpotifyManager(full_config)
    url = mgr.reauth_url()
    assert url == "https://accounts.spotify.com/authorize?x=1"


@patch("spotify_manager.spotipy")
def test_reauth_url_without_credentials(mock_spotipy, empty_config):
    from spotify_manager import SpotifyManager
    mgr = SpotifyManager(empty_config)
    assert mgr.reauth_url() is None


# ── Playback tests (go-librespot local API) ────────────────────


@patch("spotify_manager.spotipy")
@patch("spotify_manager.requests.post")
def test_play_playlist_calls_local_api(mock_post, mock_spotipy, empty_config):
    from spotify_manager import SpotifyManager

    mock_post.return_value = MagicMock(status_code=200)
    mgr = SpotifyManager(empty_config)

    result = mgr.play_playlist("spotify:playlist:XYZ")
    mock_post.assert_called_once_with(
        "http://127.0.0.1:3678/player/play",
        json={"uri": "spotify:playlist:XYZ"},
        timeout=5,
    )
    assert result is True


@patch("spotify_manager.spotipy")
@patch("spotify_manager.requests.post")
def test_play_playlist_returns_false_on_connection_error(mock_post, mock_spotipy, empty_config):
    from spotify_manager import SpotifyManager
    import requests as req

    mock_post.side_effect = req.exceptions.ConnectionError("refused")
    mgr = SpotifyManager(empty_config)

    result = mgr.play_playlist("spotify:playlist:XYZ")
    assert result is False


@patch("spotify_manager.spotipy")
@patch("spotify_manager.requests.post")
def test_next_track_calls_local_api(mock_post, mock_spotipy, empty_config):
    from spotify_manager import SpotifyManager

    mock_post.return_value = MagicMock(status_code=200)
    mgr = SpotifyManager(empty_config)

    result = mgr.next_track()
    mock_post.assert_called_once_with(
        "http://127.0.0.1:3678/player/next",
        json=None,
        timeout=5,
    )
    assert result is True


@patch("spotify_manager.spotipy")
@patch("spotify_manager.requests.post")
def test_previous_track_calls_local_api(mock_post, mock_spotipy, empty_config):
    from spotify_manager import SpotifyManager

    mock_post.return_value = MagicMock(status_code=200)
    mgr = SpotifyManager(empty_config)

    result = mgr.previous_track()
    mock_post.assert_called_once_with(
        "http://127.0.0.1:3678/player/prev",
        json=None,
        timeout=5,
    )
    assert result is True


@patch("spotify_manager.spotipy")
@patch("spotify_manager.requests.get")
def test_get_current_track_parses_status(mock_get, mock_spotipy, empty_config):
    from spotify_manager import SpotifyManager

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "paused": False,
        "track": {
            "name": "Test Song",
            "artist_names": ["Artist A", "Artist B"],
            "album_name": "Test Album",
            "album_cover_url": "http://img/cover.jpg",
        },
    }
    mock_get.return_value = mock_resp
    mgr = SpotifyManager(empty_config)

    track = mgr.get_current_track()
    assert track is not None
    assert track["name"] == "Test Song"
    assert track["artist"] == "Artist A, Artist B"
    assert track["album"] == "Test Album"
    assert track["album_art_url"] == "http://img/cover.jpg"
    assert track["is_playing"] is True


@patch("spotify_manager.spotipy")
@patch("spotify_manager.requests.get")
def test_get_current_track_returns_none_on_error(mock_get, mock_spotipy, empty_config):
    from spotify_manager import SpotifyManager
    import requests as req

    mock_get.side_effect = req.exceptions.ConnectionError("refused")
    mgr = SpotifyManager(empty_config)

    track = mgr.get_current_track()
    assert track is None


@patch("spotify_manager.spotipy")
@patch("spotify_manager.requests.get")
def test_is_connected_true_on_200(mock_get, mock_spotipy, empty_config):
    from spotify_manager import SpotifyManager

    mock_get.return_value = MagicMock(status_code=200)
    mgr = SpotifyManager(empty_config)

    assert mgr.is_connected() is True


@patch("spotify_manager.spotipy")
@patch("spotify_manager.requests.get")
def test_is_connected_false_on_connection_error(mock_get, mock_spotipy, empty_config):
    from spotify_manager import SpotifyManager
    import requests as req

    mock_get.side_effect = req.exceptions.ConnectionError("refused")
    mgr = SpotifyManager(empty_config)

    assert mgr.is_connected() is False


@patch("spotify_manager.spotipy")
@patch("spotify_manager.requests.post")
def test_set_volume_calls_local_api_with_clamped_value(mock_post, mock_spotipy, empty_config):
    from spotify_manager import SpotifyManager

    mock_post.return_value = MagicMock(status_code=200)
    mgr = SpotifyManager(empty_config)

    # Normal value
    result = mgr.set_volume(75)
    mock_post.assert_called_with(
        "http://127.0.0.1:3678/player/volume",
        json={"volume": 75},
        timeout=5,
    )
    assert result is True

    # Over 100 should clamp to 100
    mgr.set_volume(150)
    mock_post.assert_called_with(
        "http://127.0.0.1:3678/player/volume",
        json={"volume": 100},
        timeout=5,
    )

    # Below 0 should clamp to 0
    mgr.set_volume(-10)
    mock_post.assert_called_with(
        "http://127.0.0.1:3678/player/volume",
        json={"volume": 0},
        timeout=5,
    )
