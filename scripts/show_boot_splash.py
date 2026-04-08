#!/usr/bin/env python3
"""Minimal boot splash — shows boot_tiger.png on the SPI display as early
as possible in the boot sequence, long before the main flockify.py
process is ready.

Designed to be run from a systemd oneshot unit that orders itself
Before=flockify.service. The main app will overwrite this image when
it finishes initialising, so there is no visible gap.

This script intentionally has minimal imports — only spi_display_lib
and PIL — so startup time is dominated by SPI init (~0.5 s), not
Python import cost.
"""

import os
import sys

# Make project root importable
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

from PIL import Image  # noqa: E402
from lib.spi_display_lib import SPIDisplay  # noqa: E402

DISPLAY_WIDTH = 240
DISPLAY_HEIGHT = 285


def _fit(image):
    src_w, src_h = image.size
    scale = min(DISPLAY_WIDTH / src_w, DISPLAY_HEIGHT / src_h)
    new_w = max(1, int(src_w * scale))
    new_h = max(1, int(src_h * scale))
    resized = image.resize((new_w, new_h), Image.Resampling.LANCZOS)
    canvas = Image.new("RGB", (DISPLAY_WIDTH, DISPLAY_HEIGHT), (0, 0, 0))
    offset = ((DISPLAY_WIDTH - new_w) // 2, (DISPLAY_HEIGHT - new_h) // 2)
    canvas.paste(resized, offset)
    return canvas


def main():
    images_dir = os.path.join(ROOT, "images")
    boot_tiger = os.path.join(images_dir, "boot_tiger.png")
    radino = os.path.join(images_dir, "radino.png")
    path = boot_tiger if os.path.isfile(boot_tiger) else radino

    if not os.path.isfile(path):
        print(f"[boot-splash] No splash image found at {path}", file=sys.stderr)
        return 1

    try:
        img = Image.open(path).convert("RGB")
    except Exception as e:
        print(f"[boot-splash] Failed to load {path}: {e}", file=sys.stderr)
        return 1

    img = _fit(img)

    try:
        display = SPIDisplay()
        display.init()
        display.display_image(img)
        print(f"[boot-splash] Showed {os.path.basename(path)}")
    except Exception as e:
        print(f"[boot-splash] SPI display failed: {e}", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
