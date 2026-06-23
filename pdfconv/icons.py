"""Lucide-style outline icons drawn on Tk canvases.

customtkinter ships no icon set and the handoff forbids emoji, so the handful of
glyphs the UI needs are drawn as 2px-stroke outlines on small canvases scaled
from Lucide's 24x24 viewBox. Each :class:`Icon` registers its background/stroke
as theme tokens and re-renders on a theme change.
"""
from __future__ import annotations

import math
import tkinter as tk

from . import theme


def _scale(pts, size):
    s = size / 24.0
    return [v * s for p in pts for v in p]


def _line(c, size, col, w, *segments):
    for pts in segments:
        c.create_line(*_scale(pts, size), fill=col, width=w,
                      capstyle="round", joinstyle="round")


def _bbox(size, x0, y0, x1, y1):
    s = size / 24.0
    return x0 * s, y0 * s, x1 * s, y1 * s


def _ring(c, size, col, w, cx, cy, r, fill=""):
    c.create_oval(*_bbox(size, cx - r, cy - r, cx + r, cy + r),
                  outline=col, width=w, fill=fill)


# --- individual glyphs -----------------------------------------------------
def _file_check(c, S, col, w):
    _line(c, S, col, w,
          [(6, 21), (6, 3), (14, 3), (14, 8), (19, 8), (19, 21), (6, 21)],
          [(9, 14), (11, 16), (15, 12)])


def _file(c, S, col, w):
    _line(c, S, col, w,
          [(6, 21), (6, 3), (14, 3), (14, 8), (19, 8), (19, 21), (6, 21)])


def _plus(c, S, col, w):
    _line(c, S, col, w, [(12, 5), (12, 19)], [(5, 12), (19, 12)])


def _x(c, S, col, w):
    _line(c, S, col, w, [(6, 6), (18, 18)], [(18, 6), (6, 18)])


def _check(c, S, col, w):
    _line(c, S, col, w, [(20, 6), (9, 17), (4, 12)])


def _folder(c, S, col, w):
    _line(c, S, col, w,
          [(3, 17), (3, 7), (8.5, 7), (10.5, 9), (21, 9), (21, 17), (3, 17)])


def _folder_open(c, S, col, w):
    _line(c, S, col, w,
          [(3, 17), (3, 7), (8.5, 7), (10.5, 9), (19, 9)],
          [(3, 17), (6, 11), (22, 11), (19, 17), (3, 17)])


def _sun(c, S, col, w):
    _ring(c, S, col, w, 12, 12, 4)
    for a in range(0, 360, 45):
        rad = math.radians(a)
        x0, y0 = 12 + 7 * math.cos(rad), 12 + 7 * math.sin(rad)
        x1, y1 = 12 + 9.3 * math.cos(rad), 12 + 9.3 * math.sin(rad)
        _line(c, S, col, w, [(x0, y0), (x1, y1)])


def _moon(c, S, col, w):
    c.create_arc(*_bbox(S, 3, 3, 21, 21), start=40, extent=290,
                 style=tk.ARC, outline=col, width=w)


def _gear(c, S, col, w):
    _ring(c, S, col, w, 12, 12, 3)
    for a in range(0, 360, 45):
        rad = math.radians(a)
        x0, y0 = 12 + 6.5 * math.cos(rad), 12 + 6.5 * math.sin(rad)
        x1, y1 = 12 + 9.3 * math.cos(rad), 12 + 9.3 * math.sin(rad)
        _line(c, S, col, w, [(x0, y0), (x1, y1)])


def _lock(c, S, col, w):
    c.create_rectangle(*_bbox(S, 5, 11, 19, 21), outline=col, width=w)
    _line(c, S, col, w, [(8, 11), (8, 7)], [(16, 7), (16, 11)])
    c.create_arc(*_bbox(S, 8, 3, 16, 11), start=0, extent=180,
                 style=tk.ARC, outline=col, width=w)


def _refresh(c, S, col, w):
    # Two opposing arcs with small arrowheads — a circular "convert" mark.
    c.create_arc(*_bbox(S, 3.5, 3.5, 20.5, 20.5), start=70, extent=150,
                 style=tk.ARC, outline=col, width=w)
    c.create_arc(*_bbox(S, 3.5, 3.5, 20.5, 20.5), start=250, extent=150,
                 style=tk.ARC, outline=col, width=w)
    _line(c, S, col, w,
          [(20, 4), (20, 8.5), (15.5, 8.5)],
          [(4, 20), (4, 15.5), (8.5, 15.5)])


def _caret_right(c, S, col, w):
    _line(c, S, col, w, [(9, 6), (15, 12), (9, 18)])


def _caret_down(c, S, col, w):
    _line(c, S, col, w, [(6, 9), (12, 15), (18, 9)])


_ICONS = {
    "file-check": _file_check,
    "file": _file,
    "plus": _plus,
    "x": _x,
    "check": _check,
    "folder": _folder,
    "folder-open": _folder_open,
    "sun": _sun,
    "moon": _moon,
    "gear": _gear,
    "lock": _lock,
    "refresh": _refresh,
    "caret-right": _caret_right,
    "caret-down": _caret_down,
}


# --------------------------------------------------------------------------
# PIL-rendered variants for use inside CTkButton (which needs a CTkImage).
# Pillow is a hard dependency of customtkinter, so it's available; we guard the
# import anyway and let callers fall back to text-only buttons if it isn't.
# --------------------------------------------------------------------------
try:
    from PIL import Image, ImageDraw
    import customtkinter as _ctk
    _PIL_OK = True
except Exception:  # pragma: no cover
    _PIL_OK = False

_SS = 4  # supersampling factor for crisp small glyphs


def _p(pts, sc):
    return [(x * sc, y * sc) for x, y in pts]


def _arc(d, S, col, w, x0, y0, x1, y1, start, end):
    sc = S / 24.0
    d.arc([x0 * sc, y0 * sc, x1 * sc, y1 * sc], start=start, end=end, fill=col, width=w)


def _ellipse(d, S, col, w, cx, cy, r):
    sc = S / 24.0
    d.ellipse([(cx - r) * sc, (cy - r) * sc, (cx + r) * sc, (cy + r) * sc], outline=col, width=w)


def _pl(d, S, col, w, *polylines):
    sc = S / 24.0
    for pts in polylines:
        d.line(_p(pts, sc), fill=col, width=w, joint="curve")


def _pi_file(d, S, c, w):
    _pl(d, S, c, w, [(6, 21), (6, 3), (14, 3), (14, 8), (19, 8), (19, 21), (6, 21)])


def _pi_file_check(d, S, c, w):
    _pl(d, S, c, w,
        [(6, 21), (6, 3), (14, 3), (14, 8), (19, 8), (19, 21), (6, 21)],
        [(9, 14), (11, 16), (15, 12)])


def _pi_plus(d, S, c, w):
    _pl(d, S, c, w, [(12, 5), (12, 19)], [(5, 12), (19, 12)])


def _pi_x(d, S, c, w):
    _pl(d, S, c, w, [(6, 6), (18, 18)], [(18, 6), (6, 18)])


def _pi_check(d, S, c, w):
    _pl(d, S, c, w, [(20, 6), (9, 17), (4, 12)])


def _pi_folder(d, S, c, w):
    _pl(d, S, c, w, [(3, 17), (3, 7), (8.5, 7), (10.5, 9), (21, 9), (21, 17), (3, 17)])


def _pi_folder_open(d, S, c, w):
    _pl(d, S, c, w,
        [(3, 17), (3, 7), (8.5, 7), (10.5, 9), (19, 9)],
        [(3, 17), (6, 11), (22, 11), (19, 17), (3, 17)])


def _pi_lock(d, S, c, w):
    sc = S / 24.0
    d.rectangle([5 * sc, 11 * sc, 19 * sc, 21 * sc], outline=c, width=w)
    _pl(d, S, c, w, [(8, 11), (8, 7)], [(16, 7), (16, 11)])
    _arc(d, S, c, w, 8, 3, 16, 11, 180, 360)


def _pi_gear(d, S, c, w):
    _ellipse(d, S, c, w, 12, 12, 3)
    for a in range(0, 360, 45):
        rad = math.radians(a)
        _pl(d, S, c, w, [(12 + 6.5 * math.cos(rad), 12 + 6.5 * math.sin(rad)),
                         (12 + 9.3 * math.cos(rad), 12 + 9.3 * math.sin(rad))])


def _pi_sun(d, S, c, w):
    _ellipse(d, S, c, w, 12, 12, 4)
    for a in range(0, 360, 45):
        rad = math.radians(a)
        _pl(d, S, c, w, [(12 + 7 * math.cos(rad), 12 + 7 * math.sin(rad)),
                         (12 + 9.3 * math.cos(rad), 12 + 9.3 * math.sin(rad))])


def _pi_moon(d, S, c, w):
    # Outline fallback; the filled crescent is drawn in _render_moon instead.
    _arc(d, S, c, w, 3, 3, 21, 21, 40, 330)


def _pi_sliders(d, S, c, w):
    # Two horizontal tracks each with a knob — a clear "settings" glyph that
    # can't be mistaken for the sun (unlike a thin-spoked cog at 16px).
    sc = S / 24.0
    _pl(d, S, c, w, [(3, 8), (21, 8)], [(3, 16), (21, 16)])
    d.ellipse([(9 - 2.6) * sc, (8 - 2.6) * sc, (9 + 2.6) * sc, (8 + 2.6) * sc], fill=c)
    d.ellipse([(15 - 2.6) * sc, (16 - 2.6) * sc, (15 + 2.6) * sc, (16 + 2.6) * sc], fill=c)


def _pi_refresh(d, S, c, w):
    _arc(d, S, c, w, 3.5, 3.5, 20.5, 20.5, 150, 300)
    _arc(d, S, c, w, 3.5, 3.5, 20.5, 20.5, 330, 480)
    _pl(d, S, c, w, [(20, 4), (20, 8.5), (15.5, 8.5)], [(4, 20), (4, 15.5), (8.5, 15.5)])


def _pi_caret_right(d, S, c, w):
    _pl(d, S, c, w, [(9, 6), (15, 12), (9, 18)])


def _pi_caret_down(d, S, c, w):
    _pl(d, S, c, w, [(6, 9), (12, 15), (18, 9)])


_PIL_ICONS = {
    "file": _pi_file, "file-check": _pi_file_check, "plus": _pi_plus, "x": _pi_x,
    "check": _pi_check, "folder": _pi_folder, "folder-open": _pi_folder_open,
    "lock": _pi_lock, "gear": _pi_gear, "sliders": _pi_sliders, "sun": _pi_sun,
    "moon": _pi_moon, "refresh": _pi_refresh, "caret-right": _pi_caret_right,
    "caret-down": _pi_caret_down,
}


def _hex_rgba(h: str):
    h = h.lstrip("#")
    return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16), 255)


def _render_moon(img, S, color):
    """Filled crescent (disc minus an offset disc) — reads clearly at 14px."""
    from PIL import ImageChops

    sc = S / 24.0
    disc = Image.new("L", (S, S), 0)
    ImageDraw.Draw(disc).ellipse([3 * sc, 3 * sc, 21 * sc, 21 * sc], fill=255)
    bite = Image.new("L", (S, S), 0)
    ImageDraw.Draw(bite).ellipse([9 * sc, 0 * sc, 27 * sc, 18 * sc], fill=255)
    crescent = ImageChops.subtract(disc, bite)
    colored = Image.new("RGBA", (S, S), _hex_rgba(color))
    img.paste(colored, (0, 0), crescent)

_image_cache: dict = {}


def _render_pil(name: str, px: int, color: str, angle: float = 0.0):
    S = px * _SS
    img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    if name == "moon":
        _render_moon(img, S, color)
    else:
        d = ImageDraw.Draw(img)
        w = max(1, round(1.8 * _SS * (px / 16.0)))
        fn = _PIL_ICONS.get(name)
        if fn:
            fn(d, S, color, w)
    if angle:
        img = img.rotate(angle, resample=Image.BICUBIC, expand=False)
    return img


def icon_image(name: str, size: int = 15, light: str = "#64748B", dark: str = "#94A3B8"):
    """Return a theme-aware :class:`CTkImage` for *name*, or ``None`` if PIL is absent.

    A ``name@angle`` suffix (e.g. ``"refresh@90"``) renders the glyph rotated by
    that many degrees — used for the Convert-button spinner.
    """
    if not _PIL_OK:
        return None
    key = (name, size, light, dark)
    if key not in _image_cache:
        base, _, ang = name.partition("@")
        angle = float(ang) if ang else 0.0
        _image_cache[key] = _ctk.CTkImage(
            light_image=_render_pil(base, size, light, angle),
            dark_image=_render_pil(base, size, dark, angle),
            size=(size, size),
        )
    return _image_cache[key]


class Icon(tk.Canvas):
    """A small canvas rendering one named Lucide-style glyph."""

    def __init__(self, master, name, size=16, color=theme.MUTED, bg=theme.SURFACE,
                 width=1.8, **kw):
        super().__init__(master, width=size, height=size, highlightthickness=0,
                         borderwidth=0, **kw)
        self.name = name
        self.size = size
        self._color = color
        self._bg = bg
        self._w = width
        self.render()

    def render(self) -> None:
        self.delete("all")
        self.configure(bg=theme.pick(self._bg))
        fn = _ICONS.get(self.name)
        if fn:
            fn(self, self.size, theme.pick(self._color), self._w)

    def set_color(self, color) -> None:
        self._color = color
        self.render()

    def set_bg(self, bg) -> None:
        self._bg = bg
        self.render()

    def set_icon(self, name) -> None:
        self.name = name
        self.render()

    # Called by the App on a theme toggle.
    def on_theme_change(self) -> None:
        self.render()


class BrandTile(tk.Canvas):
    """The 30x30 rounded gradient brand mark with a white file-check glyph."""

    def __init__(self, master, size=30, bg=theme.BG, **kw):
        super().__init__(master, width=size, height=size, highlightthickness=0,
                         borderwidth=0, **kw)
        self.size = size
        self._bg = bg
        self.render()

    def render(self) -> None:
        self.delete("all")
        S = self.size
        self.configure(bg=theme.pick(self._bg))
        # 135deg accent->accent-hover gradient: colour is constant along each
        # anti-diagonal line x+y=k, varying from top-left to bottom-right.
        for k in range(2 * S - 1):
            t = k / max(1, 2 * (S - 1))
            col = theme.mix(theme.ACCENT, theme.ACCENT_HOVER, t)
            x0, y0 = max(0, k - (S - 1)), min(k, S - 1)
            x1, y1 = min(k, S - 1), max(0, k - (S - 1))
            self.create_line(x0, y0, x1 + 1, y1 + 1, fill=col)
        # White file-check, ~16px centred in the 30px tile.
        glyph = 16
        off = (S - glyph) / 2
        self.create_rectangle(0, 0, S, S, outline="", width=0)  # keep bbox
        c_pts = lambda pts: [off + v * (glyph / 24.0) for p in pts for v in p]
        self.create_line(*c_pts([(6, 21), (6, 3), (14, 3), (14, 8), (19, 8), (19, 21), (6, 21)]),
                         fill="#ffffff", width=1.9, capstyle="round", joinstyle="round")
        self.create_line(*c_pts([(9, 14), (11, 16), (15, 12)]),
                         fill="#ffffff", width=1.9, capstyle="round", joinstyle="round")

    def on_theme_change(self) -> None:
        self.render()
