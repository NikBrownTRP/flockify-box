"""Tests for DisplayManager (display_manager.py)."""

import pytest
from unittest.mock import patch, MagicMock

from display_manager import DisplayManager


def test_init_no_display():
    dm = DisplayManager(None)
    assert dm.display is None
    assert dm.bluetooth_active is False
    assert dm.current_image is None


def test_set_bluetooth_active():
    dm = DisplayManager(None)
    dm.set_bluetooth_active(True)
    assert dm.bluetooth_active is True


def test_set_bluetooth_toggle():
    dm = DisplayManager(None)
    dm.set_bluetooth_active(True)
    assert dm.bluetooth_active is True
    dm.set_bluetooth_active(False)
    assert dm.bluetooth_active is False


@patch("display_manager.Image")
def test_show_sleep_screen_missing_image(mock_image_module):
    """show_sleep_screen() should not crash even if image file is missing."""
    # Make Image.open raise so the except branch runs
    mock_image_module.open.side_effect = FileNotFoundError("No such file")
    # Image.new must return a mock that supports .resize()
    mock_black = MagicMock()
    mock_image_module.new.return_value = mock_black
    mock_black.resize.return_value = mock_black
    mock_image_module.LANCZOS = 1

    dm = DisplayManager(None)
    # Should not raise
    dm.show_sleep_screen()
    # Fallback black image was created
    mock_image_module.new.assert_called_once()


def test_show_webradio_missing_image():
    """show_webradio_image() should not crash with a nonexistent path."""
    dm = DisplayManager(None)
    # _load_image will fail to open the file and return None; the method logs a
    # warning and returns without crashing.
    dm.show_webradio_image("/tmp/nonexistent_image_flockify_test.png")
    # No assertion beyond "did not raise"


def test_cleanup_no_crash():
    dm = DisplayManager(None)
    dm.cleanup()
    # After cleanup, cache and current_image should be cleared
    assert dm.current_image is None
    assert len(dm.image_cache) == 0
