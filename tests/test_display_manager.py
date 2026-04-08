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


def test_volume_overlay_no_current_image():
    """show_volume_overlay should be a no-op if no current image is set."""
    dm = DisplayManager(None)
    # Should not crash
    dm.show_volume_overlay(50, 80)
    assert dm._volume_timer is None


def test_volume_overlay_renders_with_image():
    """show_volume_overlay should compose and schedule a dismiss timer."""
    from PIL import Image
    dm = DisplayManager(None)
    dm.current_image = Image.new("RGB", (240, 285), (100, 100, 100))
    dm.show_volume_overlay(40, 80)
    # A timer should be scheduled
    assert dm._volume_timer is not None
    # Cancel before the test ends so we don't leak threads
    dm._volume_timer.cancel()


def test_volume_overlay_at_max():
    """When volume == max_volume, the overlay still renders without crashing."""
    from PIL import Image
    dm = DisplayManager(None)
    dm.current_image = Image.new("RGB", (240, 285), (50, 50, 50))
    dm.show_volume_overlay(40, 40)  # at max
    assert dm._volume_timer is not None
    dm._volume_timer.cancel()


def test_volume_overlay_zero_max_no_div_zero():
    """If max_volume is 0 (e.g. nighttime), don't crash on division."""
    from PIL import Image
    dm = DisplayManager(None)
    dm.current_image = Image.new("RGB", (240, 285), (50, 50, 50))
    dm.show_volume_overlay(0, 0)
    assert dm._volume_timer is not None
    dm._volume_timer.cancel()


def test_volume_overlay_debounces_timer():
    """Rapid successive calls should reset the timer instead of stacking."""
    from PIL import Image
    dm = DisplayManager(None)
    dm.current_image = Image.new("RGB", (240, 285), (50, 50, 50))
    dm.show_volume_overlay(20, 80)
    first_timer = dm._volume_timer
    dm.show_volume_overlay(25, 80)
    second_timer = dm._volume_timer
    # New timer should replace the old one
    assert first_timer is not second_timer
    # First timer should have been cancelled
    assert not first_timer.is_alive() or first_timer.finished.is_set()
    dm._volume_timer.cancel()


def test_cleanup_cancels_volume_timer():
    """cleanup() should cancel any pending volume overlay timer."""
    from PIL import Image
    dm = DisplayManager(None)
    dm.current_image = Image.new("RGB", (240, 285), (50, 50, 50))
    dm.show_volume_overlay(40, 80)
    assert dm._volume_timer is not None
    dm.cleanup()
    assert dm._volume_timer is None
