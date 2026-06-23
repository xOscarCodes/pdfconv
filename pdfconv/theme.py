"""Design tokens — the slate & indigo system from the design handoff.

Every neutral token is a ``(light, dark)`` tuple, which is the form
customtkinter consumes directly: pass the tuple to a widget's ``fg_color`` etc.
and it follows :func:`customtkinter.set_appearance_mode` automatically. Status
colours are theme-independent (single hex), per the handoff.

Custom Tk canvases (the status dots) can't take tuples, so :func:`pick`
resolves a token to the concrete hex for the current appearance mode.
"""
from __future__ import annotations

import customtkinter as ctk

# --- Neutrals: (light, dark) -----------------------------------------------
BG          = ("#F8FAFC", "#0F172A")   # window body
SURFACE     = ("#FFFFFF", "#1E293B")   # header/footer/options strips, sticky rows
INSET       = ("#F1F5F9", "#0B1220")   # progress tracks, log background
BORDER      = ("#E2E8F0", "#334155")   # standard 1px borders
BORDER_SOFT = ("#EDF1F6", "#293650")   # hairline separators
TEXT        = ("#0F172A", "#F1F5F9")   # primary text
MUTED       = ("#64748B", "#94A3B8")   # secondary text
DESK        = ("#E2E8F0", "#070B16")   # desktop backdrop behind the window
HOVER       = ("#0F172A", "#94A3B8")   # base colour for hover washes (used low-alpha)

# --- Accent (brand, theme-independent) -------------------------------------
ACCENT       = "#6366F1"
ACCENT_HOVER = "#4F46E5"
# accent-soft differs by theme: ~10% (light) / ~18% (dark) alpha over the body.
ACCENT_SOFT  = ("#EAEBFB", "#252A4A")

# --- Status (fixed across themes) ------------------------------------------
ST_QUEUED = "#64748B"
ST_CONV   = "#F59E0B"   # converting / locked
ST_DONE   = "#22C55E"
ST_FAIL   = "#EF4444"   # failed / no-text

# Pre-mixed halo colours (status colour at ~26% over the body background),
# computed per theme so the canvas dots get a believable halo without alpha.
HALO = {
    "dark": {
        ST_QUEUED: "#2B3344",
        ST_CONV:   "#3E342A",
        ST_DONE:   "#1B3A2A",
        ST_FAIL:   "#3A2330",  # reddish wash; kept subtle
    },
    "light": {
        ST_QUEUED: "#DDE2EA",
        ST_CONV:   "#FBEBCF",
        ST_DONE:   "#D2F0DC",
        ST_FAIL:   "#FAD9D9",
    },
}

# Row completion-flash tint (green wash) per theme.
FLASH = {"dark": "#16341F", "light": "#DFF3E6"}

# --- Radii / spacing -------------------------------------------------------
R_CTRL  = 7    # buttons / inputs
R_CARD  = 12   # window / cards
R_BADGE = 4    # chips / checkboxes


def mix(hex1: str, hex2: str, t: float) -> str:
    """Blend two ``#rrggbb`` colours: ``t=0`` -> *hex1*, ``t=1`` -> *hex2*."""
    t = max(0.0, min(1.0, t))
    a = _rgb(hex1)
    b = _rgb(hex2)
    r = round(a[0] + (b[0] - a[0]) * t)
    g = round(a[1] + (b[1] - a[1]) * t)
    bl = round(a[2] + (b[2] - a[2]) * t)
    return f"#{r:02x}{g:02x}{bl:02x}"


def _rgb(h: str) -> tuple[int, int, int]:
    h = h.lstrip("#")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def pick(token, mode: str | None = None) -> str:
    """Resolve a ``(light, dark)`` token (or plain hex) to a concrete hex.

    Used for raw Tk widgets (e.g. canvases) that cannot consume colour tuples.
    """
    if mode is None:
        mode = ctk.get_appearance_mode().lower()
    if isinstance(token, (tuple, list)):
        return token[1] if mode == "dark" else token[0]
    return token


# --- Fonts -----------------------------------------------------------------
# Built lazily so a Tk root exists first (CTkFont requires one).
# Ordered by preference; :func:`_first_available` picks the first installed
# family, so each OS lands on its native UI font: Windows -> Segoe UI,
# macOS -> SF Pro / Helvetica Neue, Linux -> Inter / Ubuntu / Cantarell / DejaVu.
_SANS_STACK = (
    "Segoe UI",          # Windows
    "SF Pro Text", "SF Pro Display", "Helvetica Neue",  # macOS
    "Inter", "Ubuntu", "Cantarell", "DejaVu Sans",      # Linux
)
_MONO_STACK = (
    "Cascadia Code", "Consolas",          # Windows
    "SF Mono", "Menlo", "Monaco",         # macOS
    "DejaVu Sans Mono", "Ubuntu Mono",    # Linux
)


def _first_available(candidates: tuple[str, ...], fallback: str) -> str:
    """Return the first installed font family from *candidates*."""
    try:
        import tkinter.font as tkfont

        available = {f.lower() for f in tkfont.families()}
        for name in candidates:
            if name.lower() in available:
                return name
    except Exception:
        pass
    return fallback


class Fonts:
    """Lazily-constructed font set. Instantiate after the Tk root exists."""

    def __init__(self) -> None:
        sans = _first_available(_SANS_STACK, "sans-serif")
        mono = _first_available(_MONO_STACK, "TkFixedFont")
        self.title    = ctk.CTkFont(family=sans, size=16, weight="bold")
        self.heading  = ctk.CTkFont(family=sans, size=15, weight="bold")
        self.body     = ctk.CTkFont(family=sans, size=13)
        self.body_med = ctk.CTkFont(family=sans, size=13, weight="bold")
        self.control  = ctk.CTkFont(family=sans, size=13, weight="bold")
        self.small    = ctk.CTkFont(family=sans, size=12)
        self.caption  = ctk.CTkFont(family=sans, size=11, weight="bold")
        self.badge    = ctk.CTkFont(family=sans, size=11, weight="bold")
        self.mono     = ctk.CTkFont(family=mono, size=11)
        self.mono_sm  = ctk.CTkFont(family=mono, size=12)
        self.sans_family = sans
        self.mono_family = mono
