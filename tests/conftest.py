import pytest
import json
import os
import sys
import tempfile
import shutil
from unittest.mock import MagicMock

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config_manager import ConfigManager


@pytest.fixture
def tmp_dir():
    """Create a temporary directory and clean up after the test."""
    d = tempfile.mkdtemp()
    yield d
    shutil.rmtree(d)


@pytest.fixture
def default_config():
    """Return the dict from config_default.json."""
    default_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        'config_default.json',
    )
    with open(default_path, 'r') as f:
        return json.load(f)


@pytest.fixture
def config_manager(tmp_dir, default_config):
    """Create a ConfigManager backed by files in a temp directory."""
    default_dst = os.path.join(tmp_dir, 'config_default.json')
    config_dst = os.path.join(tmp_dir, 'config.json')

    with open(default_dst, 'w') as f:
        json.dump(default_config, f, indent=2)

    # Save original working directory and switch to tmp_dir so that the
    # atomic-save temp file (.config.json.tmp) lands in a writable place.
    orig_cwd = os.getcwd()
    os.chdir(tmp_dir)

    cm = ConfigManager(config_path=config_dst, default_path=default_dst)
    yield cm

    os.chdir(orig_cwd)


@pytest.fixture
def mock_spotify():
    """MagicMock with common spotify_manager methods stubbed."""
    mock = MagicMock()
    mock.play = MagicMock()
    mock.pause = MagicMock()
    mock.stop = MagicMock()
    mock.next_track = MagicMock()
    mock.previous_track = MagicMock()
    mock.set_volume = MagicMock()
    mock.get_current_track = MagicMock(return_value=None)
    mock.is_playing = MagicMock(return_value=False)
    return mock


@pytest.fixture
def mock_webradio():
    """MagicMock with webradio methods."""
    mock = MagicMock()
    mock.stop = MagicMock()
    mock.set_volume = MagicMock()
    mock.play_station = MagicMock()
    return mock


@pytest.fixture
def mock_display():
    """MagicMock with display methods."""
    mock = MagicMock()
    mock.show_playlist_cover = MagicMock()
    mock.show_webradio_image = MagicMock()
    mock.set_bluetooth_active = MagicMock()
    mock.show_sleep_screen = MagicMock()
    mock.set_backlight = MagicMock()
    mock.cleanup = MagicMock()
    return mock


@pytest.fixture
def mock_audio_router():
    """MagicMock with audio_router methods."""
    mock = MagicMock()
    mock.current_output = 'wired'
    mock.get_active_output = MagicMock(return_value='wired')
    return mock
