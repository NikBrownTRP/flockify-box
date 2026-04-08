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

import datetime
import json
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


def _parse_hhmm(s, default):
    try:
        h, m = s.split(":")
        return int(h) * 60 + int(m)
    except Exception:
        return default


def _in_window(minutes, start, end):
    """True if `minutes` falls in [start, end), supporting midnight wrap."""
    if start == end:
        return False
    if start < end:
        return start <= minutes < end
    # Wraps past midnight (e.g. 20:00..06:00)
    return minutes >= start or minutes < end


def _current_period(config_path):
    """Read schedule from config.json and return ('night'|'quiet'|'day').

    Intentionally duplicates a tiny bit of time_scheduler logic so the
    boot splash doesn't have to import the whole state_machine stack,
    which would defeat the point of running early in boot.
    """
    try:
        with open(config_path, "r") as f:
            cfg = json.load(f)
    except Exception:
        return "day"
    sched = cfg.get("schedule") or {}
    if not sched.get("enabled", False):
        return "day"
    now = datetime.datetime.now()
    mins = now.hour * 60 + now.minute
    night_s = _parse_hhmm(sched.get("night_start", "20:00"), 20 * 60)
    night_e = _parse_hhmm(sched.get("night_end", "06:00"), 6 * 60)
    if _in_window(mins, night_s, night_e):
        return "night"
    bed_s = _parse_hhmm(sched.get("bedtime_start", "19:00"), 19 * 60)
    bed_e = _parse_hhmm(sched.get("bedtime_end", "20:00"), 20 * 60)
    wake_s = _parse_hhmm(sched.get("wakeup_start", "06:00"), 6 * 60)
    wake_e = _parse_hhmm(sched.get("wakeup_end", "07:00"), 7 * 60)
    if _in_window(mins, bed_s, bed_e) or _in_window(mins, wake_s, wake_e):
        return "quiet"
    return "day"


def main():
    images_dir = os.path.join(ROOT, "images")
    config_path = os.path.join(ROOT, "config.json")

    period = _current_period(config_path)

    # Pick the splash image and backlight level for the current period.
    # Night: sleeping tiger at 5% so a bright boot never wakes the kid.
    # Quiet (bedtime/wakeup): boot tiger at 40%.
    # Day: boot tiger at full.
    if period == "night":
        candidate = os.path.join(images_dir, "sleep_tiger.png")
        backlight = 5
    elif period == "quiet":
        candidate = os.path.join(images_dir, "boot_tiger.png")
        backlight = 40
    else:
        candidate = os.path.join(images_dir, "boot_tiger.png")
        backlight = 100

    radino = os.path.join(images_dir, "radino.png")
    path = candidate if os.path.isfile(candidate) else radino

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
        # init() starts PWM at 100%; set the period-appropriate level
        # BEFORE pushing the image so there's no bright flash while
        # the frame buffer is being written.
        display.set_backlight(backlight)
        display.display_image(img)
        print(f"[boot-splash] period={period} image={os.path.basename(path)} backlight={backlight}%")
    except Exception as e:
        print(f"[boot-splash] SPI display failed: {e}", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
