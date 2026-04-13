"""Tests for the Flask web application (web/app.py)."""

import json
import pytest
from unittest.mock import MagicMock

from web.app import app, init_app, _parse_spotify_url


@pytest.fixture
def client():
    """Create a Flask test client with mocked subsystems."""
    # -- state_machine mock --
    sm = MagicMock()
    sm.get_status.return_value = {
        "mode": "spotify",
        "mode_index": 0,
        "volume": 50,
        "is_playing": True,
        "track": {"name": "Test Song", "artist": "Test Artist"},
    }
    sm.set_mode = MagicMock()
    sm.next_mode = MagicMock()
    sm.set_volume = MagicMock()

    # -- config_manager mock --
    cm = MagicMock()
    cm.MAX_PLAYLISTS = 10
    cm.config = {
        "schedule": {"enabled": False, "night_start": "20:00", "night_end": "07:00"},
        "playlists": [
            {"name": "Playlist 1", "uri": "spotify:playlist:AAA", "cover_url": ""},
        ],
        "webradio": {"name": "Radio", "url": "http://stream.example.com"},
        "spotify": {"client_id": "cid", "client_secret": "csec", "device_name": "flockifybox"},
        "display": {"backlight": 80},
        "max_volume": 100,
        "volume_step": 5,
    }

    def _cm_get(key, default=None):
        return cm.config.get(key, default)

    cm.get = MagicMock(side_effect=_cm_get)
    cm.set = MagicMock()
    cm.save = MagicMock()
    cm.add_playlist = MagicMock()
    cm.remove_playlist = MagicMock()
    cm.reorder_playlists = MagicMock()

    # -- spotify_manager mock --
    spm = MagicMock()
    spm.is_configured.return_value = True
    spm.is_connected.return_value = True
    spm.get_playlist_info.return_value = {
        "name": "Test",
        "cover_url": "http://img",
        "track_count": 10,
    }

    # -- bluetooth_manager mock --
    bm = MagicMock()
    bm.scan.return_value = [
        {"address": "AA:BB:CC:DD:EE:FF", "name": "Speaker", "paired": False, "connected": False},
    ]
    bm.get_paired_devices = MagicMock(return_value=[])
    bm.get_connected_device = MagicMock(return_value=None)

    init_app(sm, cm, spm, dm=None, bm=bm)

    app.config["TESTING"] = True
    with app.test_client() as test_client:
        # Attach mocks so individual tests can inspect / override them
        test_client.state_machine = sm
        test_client.config_manager = cm
        test_client.spotify_manager = spm
        test_client.bluetooth_manager = bm
        yield test_client


# ------------------------------------------------------------------
# _parse_spotify_url unit tests
# ------------------------------------------------------------------

def test_parse_spotify_url_full():
    result = _parse_spotify_url("https://open.spotify.com/playlist/ABC123?si=xxx")
    assert result == "spotify:playlist:ABC123"


def test_parse_spotify_url_uri():
    result = _parse_spotify_url("spotify:playlist:ABC123")
    assert result == "spotify:playlist:ABC123"


def test_parse_spotify_url_invalid():
    result = _parse_spotify_url("https://google.com")
    assert result is None


def test_parse_spotify_url_empty():
    result = _parse_spotify_url("")
    assert result is None


def test_parse_spotify_url_intl_locale():
    """URLs from localised Spotify clients have a locale prefix."""
    result = _parse_spotify_url("https://open.spotify.com/intl-de/playlist/ABC123?si=xxx&pi=yyy")
    assert result == "spotify:playlist:ABC123"


def test_parse_spotify_url_short_locale():
    result = _parse_spotify_url("https://open.spotify.com/de/playlist/ABC123")
    assert result == "spotify:playlist:ABC123"


def test_parse_spotify_url_legacy_user_uri():
    """Legacy spotify:user:foo:playlist:ID format."""
    result = _parse_spotify_url("spotify:user:johndoe:playlist:ABC123")
    assert result == "spotify:playlist:ABC123"


def test_parse_spotify_url_album():
    """Album URL should produce a spotify:album:ID URI."""
    result = _parse_spotify_url("https://open.spotify.com/album/7zU1NSsPQbHwXXoEHWa1g8?si=acgxFydwR_iCrj2rfjoCuA")
    assert result == "spotify:album:7zU1NSsPQbHwXXoEHWa1g8"


def test_parse_spotify_url_album_intl():
    result = _parse_spotify_url("https://open.spotify.com/intl-de/album/7zU1NSsPQbHwXXoEHWa1g8")
    assert result == "spotify:album:7zU1NSsPQbHwXXoEHWa1g8"


def test_parse_spotify_url_album_uri():
    result = _parse_spotify_url("spotify:album:7zU1NSsPQbHwXXoEHWa1g8")
    assert result == "spotify:album:7zU1NSsPQbHwXXoEHWa1g8"


# ------------------------------------------------------------------
# Page route tests
# ------------------------------------------------------------------

def test_dashboard_200(client):
    resp = client.get("/")
    assert resp.status_code == 200


def test_playlists_page_200(client):
    resp = client.get("/playlists")
    assert resp.status_code == 200


def test_settings_page_200(client):
    resp = client.get("/settings")
    assert resp.status_code == 200


# ------------------------------------------------------------------
# API tests
# ------------------------------------------------------------------

def test_api_status_json(client):
    resp = client.get("/api/status")
    assert resp.status_code == 200
    data = resp.get_json()
    assert "mode" in data


def test_api_add_playlist_invalid_url(client):
    resp = client.post(
        "/api/playlists",
        data=json.dumps({"url": "not-a-url"}),
        content_type="application/json",
    )
    assert resp.status_code == 400


def test_api_remove_playlist(client):
    resp = client.delete("/api/playlists/0")
    assert resp.status_code == 200
    client.config_manager.remove_playlist.assert_called_once_with(0)


def test_api_volume(client):
    resp = client.post(
        "/api/volume",
        data=json.dumps({"volume": 60}),
        content_type="application/json",
    )
    assert resp.status_code == 200
    client.state_machine.set_volume.assert_called_once_with(60)


def test_api_next_mode(client):
    resp = client.post("/api/next_mode")
    assert resp.status_code == 200
    client.state_machine.next_mode.assert_called_once()


def test_api_schedule(client):
    resp = client.post(
        "/api/schedule",
        data=json.dumps({"enabled": True}),
        content_type="application/json",
    )
    assert resp.status_code == 200
    client.config_manager.set.assert_called()
    # Verify 'schedule' was the first arg of the set() call
    args, _ = client.config_manager.set.call_args
    assert args[0] == "schedule"
    assert args[1]["enabled"] is True


def test_api_bt_scan(client):
    resp = client.post("/api/bluetooth/scan")
    assert resp.status_code == 200
    data = resp.get_json()
    assert isinstance(data, list)
    assert data[0]["address"] == "AA:BB:CC:DD:EE:FF"


def test_api_bt_no_manager(client):
    import web.app as webapp
    original_bm = webapp.bluetooth_manager
    webapp.bluetooth_manager = None
    try:
        resp = client.post("/api/bluetooth/scan")
        assert resp.status_code == 503
    finally:
        webapp.bluetooth_manager = original_bm


def test_api_spotify_logout(client):
    import web.app as webapp
    resp = client.post("/api/spotify/logout")
    assert resp.status_code == 200
    assert resp.get_json() == {"ok": True}
    webapp.spotify_manager.logout.assert_called_once()


def test_api_spotify_clear(client):
    import web.app as webapp
    resp = client.post("/api/spotify/clear")
    assert resp.status_code == 200
    assert resp.get_json() == {"ok": True}
    webapp.spotify_manager.clear_credentials.assert_called_once()


def test_api_spotify_reauth_with_creds(client):
    import web.app as webapp
    webapp.spotify_manager.reauth_url.return_value = "https://accounts.spotify.com/authorize?x=1"
    resp = client.post("/api/spotify/reauth")
    assert resp.status_code == 200
    assert resp.get_json()["auth_url"].startswith("https://")


def test_api_spotify_reauth_no_creds(client):
    import web.app as webapp
    webapp.spotify_manager.reauth_url.return_value = None
    resp = client.post("/api/spotify/reauth")
    assert resp.status_code == 400


# ------------------------------------------------------------------
# Playlist period restriction API tests
# ------------------------------------------------------------------

def test_api_update_playlist_periods(client):
    resp = client.patch(
        "/api/playlists/0",
        data=json.dumps({"allowed_periods": ["day"]}),
        content_type="application/json",
    )
    assert resp.status_code == 200
    assert resp.get_json() == {"ok": True}
    client.config_manager.update_playlist.assert_called_once_with(0, {"allowed_periods": ["day"]})


def test_api_update_playlist_invalid_periods(client):
    resp = client.patch(
        "/api/playlists/0",
        data=json.dumps({"allowed_periods": ["night"]}),
        content_type="application/json",
    )
    assert resp.status_code == 400
