#!/usr/bin/env python3
"""Generate the Flockify Box PWA/iOS app icons.

Design: warm amber radial-gradient background in a rounded square, tiger
mascot (from images/boot_tiger.png) centered with safe-area padding.
"""
from pathlib import Path
from PIL import Image, ImageDraw, ImageFilter

ROOT = Path(__file__).resolve().parent.parent
TIGER_SRC = ROOT / "images" / "boot_tiger.png"
OUT = ROOT / "web" / "static" / "img"

# Palette — mirrors style.css / docs
AMBER = (245, 158, 11)
AMBER_LIGHT = (253, 230, 138)
CREAM = (255, 251, 245)
CREAM_DARK = (255, 243, 224)
BROWN = (61, 41, 20)


def _square_crop_tiger() -> Image.Image:
    """Center-crop the tiger PNG to a square, scaled nicely."""
    tiger = Image.open(TIGER_SRC).convert("RGBA")
    tw, th = tiger.size
    side = min(tw, th)
    # Shift the crop upward so the head+torso are well centered, not the feet
    top = max(0, int((th - side) * 0.30))
    left = (tw - side) // 2
    return tiger.crop((left, top, left + side, top + side))


def make_icon(size: int, rounded: bool = True, bleed: bool = False) -> Image.Image:
    """Render the icon at the given size.

    The tiger art ships with a warm peach/cream gradient built-in, so we
    center-crop it to square and let it bleed to the icon edges. iOS and
    PWA launchers apply their own mask.
    """
    # Start from a cream fallback so any transparent pixels blend.
    img = Image.new("RGBA", (size, size), CREAM + (255,))

    tiger = _square_crop_tiger()
    tiger = tiger.resize((size, size), Image.LANCZOS)
    img.alpha_composite(tiger, (0, 0))

    # Amber "now playing" dot in upper-right — ties to the brand
    dd = ImageDraw.Draw(img, "RGBA")
    dot_r = max(5, size // 22)
    dot_margin = max(6, size // 12)
    dx = size - dot_margin - dot_r * 2
    dy = dot_margin
    # soft amber halo
    halo = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    hd = ImageDraw.Draw(halo)
    hd.ellipse(
        [dx - dot_r, dy - dot_r, dx + dot_r * 3, dy + dot_r * 3],
        fill=(AMBER[0], AMBER[1], AMBER[2], 70),
    )
    halo = halo.filter(ImageFilter.GaussianBlur(size / 50))
    img.alpha_composite(halo)
    # the dot itself, white ring + amber fill
    dd.ellipse(
        [dx - 2, dy - 2, dx + dot_r * 2 + 2, dy + dot_r * 2 + 2],
        fill=(255, 255, 255, 230),
    )
    dd.ellipse([dx, dy, dx + dot_r * 2, dy + dot_r * 2], fill=AMBER)

    if rounded and not bleed:
        mask = Image.new("L", (size, size), 0)
        md = ImageDraw.Draw(mask)
        radius = int(size * 0.22)
        md.rounded_rectangle([0, 0, size, size], radius=radius, fill=255)
        rounded_img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
        rounded_img.paste(img, (0, 0), mask)
        return rounded_img

    return img


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)

    # iOS home-screen: 180x180, no need for rounded corners (iOS masks it).
    apple = make_icon(180, rounded=False, bleed=True)
    apple.save(OUT / "apple-touch-icon.png", "PNG", optimize=True)

    # PWA icons: full-bleed maskable-friendly squares.
    make_icon(192, rounded=False, bleed=True).save(
        OUT / "icon-192.png", "PNG", optimize=True
    )
    make_icon(512, rounded=False, bleed=True).save(
        OUT / "icon-512.png", "PNG", optimize=True
    )

    # Favicons — rounded so they look good on light/dark browser tabs.
    fav32 = make_icon(32, rounded=True)
    fav32.save(OUT / "favicon-32.png", "PNG", optimize=True)

    # Multi-size .ico (16, 32, 48)
    sizes = [16, 32, 48]
    fav_images = [make_icon(s, rounded=True) for s in sizes]
    fav_images[0].save(
        OUT / "favicon.ico", format="ICO",
        sizes=[(s, s) for s in sizes],
        append_images=fav_images[1:],
    )

    print("Wrote icons to", OUT)


if __name__ == "__main__":
    main()
