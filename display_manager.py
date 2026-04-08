#!/usr/bin/env python3
"""
Display Manager for Flockify Box
Wraps SPIDisplay to handle playlist covers, webradio images, and Bluetooth icon overlay.
"""

import os
import logging
from collections import OrderedDict
from PIL import Image

logger = logging.getLogger(__name__)

DISPLAY_WIDTH = 240
DISPLAY_HEIGHT = 285
BT_ICON_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "images", "bluetooth_icon.png")
CACHE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "images", "cache")
IMAGE_CACHE_MAX = 12


class DisplayManager:
    """Manages the SPI display, including image loading, caching, and Bluetooth icon compositing."""

    def __init__(self, display=None):
        """
        Initialize the DisplayManager.

        Args:
            display: Optional SPIDisplay instance. If None, display calls are no-ops.
        """
        self.display = display
        self.bluetooth_active = False
        self.current_image = None  # PIL Image currently shown (without BT overlay)
        self.image_cache = OrderedDict()  # path -> PIL Image, max IMAGE_CACHE_MAX entries

    def show_playlist_cover(self, playlist_dict):
        """
        Display a playlist cover image from the cached path.

        Args:
            playlist_dict: dict with at least 'cover_cached' key pointing to cached image path.

        Returns:
            True if image was displayed, False if cached file not found on disk.
        """
        cover_path = playlist_dict.get("cover_cached")
        if not cover_path or not os.path.isfile(cover_path):
            logger.warning("Playlist cover not found on disk: %s", cover_path)
            return False

        image = self._load_image(cover_path)
        if image is None:
            return False

        image = self._fit_to_display(image)

        self.current_image = image
        display_image = self._composite_bt_icon(image) if self.bluetooth_active else image
        self._send_to_display(display_image)
        return True

    def show_webradio_image(self, image_path):
        """
        Display a webradio station image.

        Args:
            image_path: Path to the image file.
        """
        image = self._load_image(image_path)
        if image is None:
            logger.warning("Webradio image not found: %s", image_path)
            return

        image = self._fit_to_display(image)

        self.current_image = image
        display_image = self._composite_bt_icon(image) if self.bluetooth_active else image
        self._send_to_display(display_image)

    def set_bluetooth_active(self, active):
        """
        Update Bluetooth active state. Redraws current image if state changed.

        Args:
            active: bool indicating whether Bluetooth audio is active.
        """
        if self.bluetooth_active == active:
            return

        self.bluetooth_active = active

        # Redraw current image with or without BT icon
        if self.current_image is not None:
            display_image = self._composite_bt_icon(self.current_image) if self.bluetooth_active else self.current_image
            self._send_to_display(display_image)

    def cache_playlist_cover(self, playlist_dict, image_data_or_url):
        """
        Download/process and cache a playlist cover image.

        Args:
            playlist_dict: dict with at least 'index' key. 'cover_cached' will be set.
            image_data_or_url: Either a URL string (starting with http) or raw image bytes.

        Returns:
            The saved file path, or None on failure.
        """
        import io

        try:
            if isinstance(image_data_or_url, str) and image_data_or_url.startswith("http"):
                import requests
                response = requests.get(image_data_or_url, timeout=10)
                response.raise_for_status()
                image_bytes = response.content
            else:
                image_bytes = image_data_or_url

            image = Image.open(io.BytesIO(image_bytes))
            # Save the ORIGINAL image (preserving aspect ratio).
            # show_playlist_cover will letterbox it to display dimensions
            # at draw time. This way the cache survives display size changes
            # and the original aspect ratio is never lost.

            os.makedirs(CACHE_DIR, exist_ok=True)
            index = playlist_dict.get("index", 0)
            save_path = os.path.join(CACHE_DIR, f"playlist_{index}.jpg")

            image.convert("RGB").save(save_path, "JPEG", quality=90)
            playlist_dict["cover_cached"] = save_path

            # Update image cache
            self.image_cache.pop(save_path, None)
            self.image_cache[save_path] = image
            if len(self.image_cache) > IMAGE_CACHE_MAX:
                self.image_cache.popitem(last=False)

            logger.info("Cached playlist cover to %s", save_path)
            return save_path

        except Exception as e:
            logger.error("Failed to cache playlist cover: %s", e)
            return None

    def show_splash(self, image_path):
        """
        Display a splash image on startup.

        Args:
            image_path: Path to the splash image.
        """
        image = self._load_image(image_path)
        if image is None:
            logger.warning("Splash image not found: %s", image_path)
            return

        image = self._fit_to_display(image)
        self.current_image = image
        self._send_to_display(image)

    def show_sleep_screen(self):
        """Display the sleeping tiger image on the screen."""
        sleep_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "images", "sleep_tiger.png")
        try:
            img = Image.open(sleep_path).convert('RGB')
            img = self._fit_to_display(img)
        except Exception as e:
            # Fallback: black screen if image not found
            print(f"[display] Could not load sleep image: {e}")
            img = Image.new('RGB', (DISPLAY_WIDTH, DISPLAY_HEIGHT), (0, 0, 0))
        self.current_image = img
        self._send_to_display(img)

    def set_backlight(self, brightness):
        """
        Set display backlight brightness.

        Args:
            brightness: 0-100 (0 = off, 100 = full brightness).
        """
        if self.display is not None:
            self.display.set_backlight(brightness)

    def _load_image(self, path):
        """
        Load a PIL Image from path, using an in-memory cache.

        Args:
            path: File path to the image.

        Returns:
            PIL Image or None if loading fails.
        """
        if path in self.image_cache:
            # Move to end (most recently used)
            self.image_cache.move_to_end(path)
            return self.image_cache[path].copy()

        try:
            image = Image.open(path)
            image.load()  # Force load into memory

            # Add to cache, evict oldest if full
            self.image_cache[path] = image
            if len(self.image_cache) > IMAGE_CACHE_MAX:
                self.image_cache.popitem(last=False)

            return image.copy()

        except Exception as e:
            logger.error("Failed to load image %s: %s", path, e)
            return None

    def _fit_to_display(self, image):
        """
        Resize image to fit the display while preserving aspect ratio.
        The resized image is centered on a black canvas of exact display size.

        Args:
            image: PIL Image of any size.

        Returns:
            A new PIL Image of size (DISPLAY_WIDTH, DISPLAY_HEIGHT).
        """
        src_w, src_h = image.size
        scale = min(DISPLAY_WIDTH / src_w, DISPLAY_HEIGHT / src_h)
        new_w = max(1, int(src_w * scale))
        new_h = max(1, int(src_h * scale))

        resized = image.resize((new_w, new_h), Image.Resampling.LANCZOS)

        canvas = Image.new("RGB", (DISPLAY_WIDTH, DISPLAY_HEIGHT), (0, 0, 0))
        offset = ((DISPLAY_WIDTH - new_w) // 2, (DISPLAY_HEIGHT - new_h) // 2)
        canvas.paste(resized, offset)
        return canvas

    def _composite_bt_icon(self, image):
        """
        Paste the Bluetooth icon onto the top-right corner of the image.

        Args:
            image: PIL Image to composite onto.

        Returns:
            New PIL Image with BT icon composited.
        """
        composited = image.copy().convert("RGBA")

        try:
            bt_icon = self._load_image(BT_ICON_PATH)
            if bt_icon is None:
                logger.warning("Bluetooth icon not found at %s", BT_ICON_PATH)
                return image

            bt_icon = bt_icon.convert("RGBA").resize((24, 24), Image.Resampling.LANCZOS)

            # Position at top-right corner. Use generous inset so the icon
            # is not clipped by the rounded display bezel.
            margin = 16
            x = composited.width - bt_icon.width - margin
            y = margin

            composited.paste(bt_icon, (x, y), bt_icon)

        except Exception as e:
            logger.error("Failed to composite BT icon: %s", e)
            return image

        return composited.convert("RGB")

    def _send_to_display(self, image):
        """
        Send a PIL Image to the physical display.

        Note: Callers are responsible for setting self.current_image (the base
        image without BT overlay) before calling this method.

        Args:
            image: PIL Image to display (may include BT overlay).
        """
        if self.display is not None:
            try:
                self.display.display_image(image)
            except Exception as e:
                logger.error("Failed to send image to display: %s", e)

    def cleanup(self):
        """Clean up display resources."""
        if self.display is not None:
            try:
                self.display.cleanup()
            except Exception as e:
                logger.error("Failed to cleanup display: %s", e)
        self.image_cache.clear()
        self.current_image = None
