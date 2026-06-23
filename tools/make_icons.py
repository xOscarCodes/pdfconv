#!/usr/bin/env python3
"""Generate the application icon assets from the in-app brand mark.

Reproduces ``pdfconv.icons.BrandTile`` (a 135° indigo gradient rounded tile with
a white Lucide "file-check" glyph) at high resolution and writes:

    pdfconv/assets/icon.png    (1024x1024 master, used on Linux + as the Tk window icon)
    pdfconv/assets/icon.ico    (multi-size, Windows)
    pdfconv/assets/icon.icns   (macOS .app bundle)

Run once after checkout / when the brand changes::

    python tools/make_icons.py

Idempotent and deterministic — no network, no randomness.
"""
from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image, ImageDraw

# Brand tokens, matching pdfconv/theme.py.
ACCENT = (0x63, 0x66, 0xF1)
ACCENT_HOVER = (0x4F, 0x46, 0xE5)

ASSETS = Path(__file__).resolve().parent.parent / "pdfconv" / "assets"

# Lucide "file-check" on a 24x24 viewBox.
_OUTLINE = [(6, 21), (6, 3), (14, 3), (14, 8), (19, 8), (19, 21), (6, 21)]
_CHECK = [(9, 14), (11, 16), (15, 12)]


def _mix(a, b, t):
    return tuple(round(a[i] + (b[i] - a[i]) * t) for i in range(3))


def render(px: int) -> Image.Image:
    """Render the brand mark at *px* x *px* (supersampled then downscaled)."""
    ss = 2
    n = px * ss

    # 135° gradient: colour is constant along each anti-diagonal x + y = k.
    grad = Image.new("RGB", (n, n))
    gd = ImageDraw.Draw(grad)
    span = max(1, 2 * (n - 1))
    for k in range(2 * n - 1):
        col = _mix(ACCENT, ACCENT_HOVER, k / span)
        x0, y0 = max(0, k - (n - 1)), min(k, n - 1)
        x1, y1 = min(k, n - 1), max(0, k - (n - 1))
        gd.line([(x0, y0), (x1 + 1, y1 + 1)], fill=col, width=1)

    # Rounded-square alpha mask (~22% corner radius — a friendly app-icon shape).
    mask = Image.new("L", (n, n), 0)
    ImageDraw.Draw(mask).rounded_rectangle(
        [0, 0, n - 1, n - 1], radius=int(n * 0.2235), fill=255
    )

    tile = Image.new("RGBA", (n, n), (0, 0, 0, 0))
    tile.paste(grad, (0, 0), mask)

    # White file-check glyph, centred at ~50% of the tile.
    draw = ImageDraw.Draw(tile)
    glyph = n * 0.5
    off = (n - glyph) / 2
    sc = glyph / 24.0
    white = (255, 255, 255, 255)
    w = max(1, round(glyph * (2.1 / 24)))

    def pts(poly):
        return [(off + x * sc, off + y * sc) for x, y in poly]

    for poly in (_OUTLINE, _CHECK):
        p = pts(poly)
        draw.line(p, fill=white, width=w, joint="curve")
        r = w / 2  # round the joints/ends (PIL has no round cap natively)
        for x, y in p:
            draw.ellipse([x - r, y - r, x + r, y + r], fill=white)

    return tile.resize((px, px), Image.LANCZOS)


def main() -> int:
    ASSETS.mkdir(parents=True, exist_ok=True)
    master = render(1024)

    png = ASSETS / "icon.png"
    master.save(png)
    print(f"wrote {png}")

    ico = ASSETS / "icon.ico"
    master.save(
        ico,
        sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)],
    )
    print(f"wrote {ico}")

    icns = ASSETS / "icon.icns"
    try:
        master.save(icns)
        print(f"wrote {icns}")
    except Exception as exc:  # pragma: no cover - platform/Pillow dependent
        print(f"WARNING: could not write {icns}: {exc}", file=sys.stderr)
        print(
            "         macOS users can generate it from icon.png with iconutil "
            "(see README).",
            file=sys.stderr,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
