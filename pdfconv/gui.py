"""customtkinter GUI — the App surface from the design handoff.

Implements the single-window converter: header, action row, selection bar,
scrollable queue with the signature live status system, options strip, and a
footer with progress, controls and a collapsible log, plus a settings drawer
and a password dialog.

Threading model (non-functional requirement): all conversion happens in a
``ProcessPoolExecutor`` driven by a background manager thread. That thread never
touches Tk — it posts events onto a :class:`queue.Queue` which the main thread
drains via ``after`` and applies to widgets. The UI therefore stays responsive
through large batches.
"""
from __future__ import annotations

import logging
import math
import multiprocessing
import os
import platform
import queue
import sys
import threading
import time
from concurrent.futures import FIRST_COMPLETED, ProcessPoolExecutor, wait
from datetime import datetime
from pathlib import Path
from tkinter import filedialog, messagebox

import customtkinter as ctk

from . import __version__, audit, config, engine, logsetup, platform_utils, theme
from .icons import BrandTile, icon_image

log = logging.getLogger("pdfconv")

REDUCED_MOTION = bool(os.environ.get("PDFCONV_REDUCED_MOTION"))

HOVER_WASH = ("#EEF1F6", "#222C3E")   # subtle hover background for ghost controls
ROW_HOVER = ("#F3F5F9", "#1A2740")    # queue row hover background


# ---------------------------------------------------------------------------
# Status dot — canvas widget with halo + optional pulse
# ---------------------------------------------------------------------------
class StatusDot(ctk.CTkCanvas):
    SIZE = 16

    def __init__(self, master, bg=theme.BG):
        super().__init__(master, width=self.SIZE, height=self.SIZE,
                         highlightthickness=0, borderwidth=0)
        self._bg = bg
        self._color = theme.ST_QUEUED
        self._pulsing = False
        self._job = None
        self._phase = 0.0
        self.render()

    def render(self, fill=None):
        self.delete("all")
        self.configure(bg=theme.pick(self._bg))
        col = self._color
        mode = ctk.get_appearance_mode().lower()
        halo = theme.HALO.get(mode, {}).get(col) or theme.mix(theme.pick(self._bg), col, 0.3)
        self.create_oval(1, 1, 15, 15, fill=halo, outline="")
        self.create_oval(4, 4, 12, 12, fill=(fill or col), outline="")

    def set_status(self, color, pulse=False):
        self.stop_pulse()
        self._color = color
        self.render()
        if pulse and not REDUCED_MOTION:
            self._pulsing = True
            self._phase = 0.0
            self._tick()

    def _tick(self):
        if not self._pulsing or not self.winfo_exists():
            return
        v = 0.28 + 0.72 * (0.5 * (1 + math.cos(self._phase)))
        dim = theme.mix(theme.pick(self._bg), self._color, v)
        self.render(fill=dim)
        self._phase += math.pi / 9   # ~1.1s full cycle at 60ms steps
        self._job = self.after(60, self._tick)

    def stop_pulse(self):
        self._pulsing = False
        if self._job is not None:
            try:
                self.after_cancel(self._job)
            except Exception:
                pass
            self._job = None

    def on_theme_change(self):
        if not self._pulsing:
            self.render()

    def destroy(self):
        self.stop_pulse()
        super().destroy()


# ---------------------------------------------------------------------------
# Segmented control — two/three exclusive pill buttons
# ---------------------------------------------------------------------------
class SegmentedControl(ctk.CTkFrame):
    def __init__(self, master, options, command, value=None, font=None,
                 icons=None, seg_height=26, track_bg=theme.SURFACE):
        super().__init__(master, fg_color=track_bg, border_color=theme.BORDER,
                         border_width=1, corner_radius=8)
        self.command = command
        self.value = value if value is not None else options[0][0]
        self.buttons: dict[str, ctk.CTkButton] = {}
        for val, label in options:
            has_icon = bool(icons and icons.get(val) is not None)
            b = ctk.CTkButton(
                self, text=label, height=seg_height, corner_radius=6,
                width=self._seg_width(label, has_icon, font),
                fg_color="transparent", font=font,
                image=(icons or {}).get(val),
                command=lambda v=val: self._select(v),
            )
            b.pack(side="left", padx=0, pady=0)
            self.buttons[val] = b
        self._restyle()

    @staticmethod
    def _seg_width(label, has_icon, font) -> int:
        """Size a segment to its content (CTkButton otherwise defaults to 140px)."""
        text_w = 0
        if label:
            try:
                import tkinter.font as tkfont
                mf = tkfont.Font(family=font.cget("family"), size=font.cget("size"),
                                 weight=font.cget("weight")) if font is not None else None
                text_w = mf.measure(label) if mf else len(label) * 8
            except Exception:
                text_w = len(label) * 8
        icon_w = 20 if has_icon else 0
        if not label:
            return max(30, icon_w + 12)
        return text_w + icon_w + 22

    def _select(self, val):
        if val == self.value:
            return
        self.value = val
        self._restyle()
        self.command(val)

    def set(self, val):
        self.value = val
        self._restyle()

    def _restyle(self):
        for val, b in self.buttons.items():
            if val == self.value:
                b.configure(fg_color=theme.ACCENT_SOFT, text_color=theme.ACCENT,
                            hover_color=theme.ACCENT_SOFT)
            else:
                b.configure(fg_color="transparent", text_color=theme.MUTED,
                            hover_color=HOVER_WASH)


# ---------------------------------------------------------------------------
# File model + queue row
# ---------------------------------------------------------------------------
class FileItem:
    __slots__ = ("id", "path", "name", "dir", "pages", "status", "message",
                 "progress", "selected", "password", "mirror_root", "row")

    def __init__(self, fid: int, path: Path, pages: int, status: str,
                 mirror_root: Path | None = None):
        self.id = fid
        self.path = path
        self.name = path.name
        self.dir = _display_dir(path.parent)
        self.pages = pages
        self.status = status
        self.message = ""
        self.progress = 0.0
        self.selected = False
        self.password: str | None = None
        # The folder this file was discovered under (for mirror-subfolders); for
        # individually-added files it's the file's own parent.
        self.mirror_root = mirror_root if mirror_root is not None else path.parent
        self.row: "FileRow | None" = None


def _display_dir(p: Path) -> str:
    try:
        home = Path.home()
        rel = p.relative_to(home)
        return "~/" + str(rel).replace("\\", "/")
    except Exception:
        return str(p)


_STATUS_DISPLAY = {
    engine.QUEUED: ("Queued", theme.ST_QUEUED),
    engine.CONVERTING: ("Converting", theme.ST_CONV),
    engine.SCANNING: ("Running OCR", theme.ST_CONV),
    engine.DONE: ("Done", theme.ST_DONE),
    engine.NOTEXT: ("No text", theme.ST_FAIL),
    engine.FAILED: ("Failed", theme.ST_FAIL),
    engine.ENCRYPTED: ("Locked", theme.ST_CONV),
}

_COLS = ((0, 30), (1, 0), (2, 64), (3, 60), (4, 158), (5, 30))


def _configure_columns(frame):
    for col, minsize in _COLS:
        if col == 1:
            frame.grid_columnconfigure(col, weight=1, minsize=130)
        else:
            frame.grid_columnconfigure(col, minsize=minsize, weight=0)


class FileRow(ctk.CTkFrame):
    """One queue row: checkbox · file · pages · format · status · remove."""

    def __init__(self, master, app: "App", item: FileItem):
        super().__init__(master, fg_color=theme.BG, corner_radius=0, height=52)
        self.app = app
        self.item = item
        item.row = self

        # Amber left rail (shown while converting).
        self.rail = ctk.CTkFrame(self, width=2, fg_color="transparent", corner_radius=0)
        self.rail.pack(side="left", fill="y")

        self.body = ctk.CTkFrame(self, fg_color="transparent")
        self.body.pack(side="left", fill="both", expand=True)
        _configure_columns(self.body)

        # col 0 — selection checkbox
        self.check = ctk.CTkCheckBox(
            self.body, text="", width=18, checkbox_width=17, checkbox_height=17,
            corner_radius=4, border_width=2, fg_color=theme.ACCENT,
            hover_color=theme.ACCENT_HOVER, border_color=theme.MUTED,
            command=self._on_check,
        )
        self.check.grid(row=0, column=0, padx=(18, 0), pady=11, sticky="w")

        # col 1 — file icon + name + dir
        filecell = ctk.CTkFrame(self.body, fg_color="transparent")
        filecell.grid(row=0, column=1, sticky="ew", padx=(10, 6))
        ic = icon_image("file", 17, theme.MUTED[0], theme.MUTED[1])
        self.file_icon = ctk.CTkLabel(filecell, text="", image=ic)
        self.file_icon.pack(side="left", padx=(0, 11))
        textcell = ctk.CTkFrame(filecell, fg_color="transparent")
        textcell.pack(side="left", fill="x", expand=True)
        self.name_lbl = ctk.CTkLabel(textcell, text=item.name, anchor="w",
                                     font=app.fonts.body_med, text_color=theme.TEXT)
        self.name_lbl.pack(fill="x")
        self.dir_lbl = ctk.CTkLabel(textcell, text=item.dir, anchor="w",
                                    font=app.fonts.mono, text_color=theme.MUTED)
        self.dir_lbl.pack(fill="x")

        # col 2 — pages
        self.pages_lbl = ctk.CTkLabel(self.body, text=_pages_label(item), anchor="w",
                                      font=app.fonts.small, text_color=theme.MUTED)
        self.pages_lbl.grid(row=0, column=2, sticky="w", padx=10)

        # col 3 — format tag
        self.fmt_lbl = ctk.CTkLabel(self.body, text=app.fmt_tag(), anchor="w",
                                    font=app.fonts.badge, text_color=theme.MUTED)
        self.fmt_lbl.grid(row=0, column=3, sticky="w", padx=10)

        # col 4 — status cell
        statuscell = ctk.CTkFrame(self.body, fg_color="transparent")
        statuscell.grid(row=0, column=4, sticky="w", padx=10)
        topline = ctk.CTkFrame(statuscell, fg_color="transparent")
        topline.pack(anchor="w")
        self.dot = StatusDot(topline, bg=theme.BG)
        self.dot.pack(side="left", padx=(0, 7))
        self.status_lbl = ctk.CTkLabel(topline, text="", font=app.fonts.body_med)
        self.status_lbl.pack(side="left")
        self.unlock_btn = ctk.CTkButton(
            topline, text="Unlock", height=21, width=0, corner_radius=5,
            font=app.fonts.badge, fg_color=theme.ACCENT_SOFT, text_color=theme.ACCENT,
            hover_color=theme.ACCENT_SOFT, border_width=1, border_color=theme.ACCENT,
            image=icon_image("lock", 11, theme.ACCENT, theme.ACCENT),
            command=self._on_unlock,
        )
        self.progress = ctk.CTkProgressBar(
            statuscell, height=4, width=130, corner_radius=2,
            fg_color=theme.INSET, progress_color=theme.ST_CONV,
        )
        self.progress.set(0)

        # col 5 — remove button (revealed on hover)
        self.remove_btn = ctk.CTkButton(
            self.body, text="", width=24, height=24, corner_radius=5,
            fg_color="transparent", hover_color=HOVER_WASH,
            image=icon_image("x", 14, theme.MUTED[0], theme.MUTED[1]),
            command=self._on_remove,
        )
        self.remove_btn.grid(row=0, column=5, padx=(0, 18))
        self.remove_btn.grid_remove()

        self.app.register_canvas(self.dot)
        self._bind_hover()
        self.refresh()

    # -- hover handling -------------------------------------------------
    def _bind_hover(self):
        self._hide_job = None
        widgets = [self, self.body, self.file_icon, self.name_lbl, self.dir_lbl,
                   self.pages_lbl, self.fmt_lbl, self.status_lbl]
        for w in widgets:
            w.bind("<Enter>", self._on_enter, add="+")
            w.bind("<Leave>", self._on_leave, add="+")

    def _on_enter(self, _e=None):
        if self._hide_job:
            self.after_cancel(self._hide_job)
            self._hide_job = None
        self.configure(fg_color=ROW_HOVER)
        self.remove_btn.grid()

    def _on_leave(self, _e=None):
        if self._hide_job:
            self.after_cancel(self._hide_job)
        self._hide_job = self.after(60, self._do_hide)

    def _do_hide(self):
        if not self.winfo_exists():
            return
        self.configure(fg_color=theme.BG)
        self.remove_btn.grid_remove()

    def destroy(self):
        if getattr(self, "_hide_job", None):
            try:
                self.after_cancel(self._hide_job)
            except Exception:
                pass
            self._hide_job = None
        super().destroy()  # the StatusDot child cancels its own pulse on destroy

    # -- callbacks ------------------------------------------------------
    def _on_check(self):
        self.item.selected = bool(self.check.get())
        self.app.on_selection_changed()

    def _on_remove(self):
        self.app.remove_item(self.item)

    def _on_unlock(self):
        self.app.unlock_item(self.item)

    # -- visual refresh -------------------------------------------------
    def refresh(self):
        item = self.item
        label, color = _STATUS_DISPLAY.get(item.status, ("Queued", theme.ST_QUEUED))
        self.status_lbl.configure(text=label, text_color=color)
        self.fmt_lbl.configure(text=self.app.fmt_tag())
        self.pages_lbl.configure(text=_pages_label(item))
        self.dot.set_status(color, pulse=(item.status in (engine.CONVERTING, engine.SCANNING)))

        # left rail while converting
        if item.status in (engine.CONVERTING, engine.SCANNING):
            self.rail.configure(fg_color=theme.ST_CONV)
        else:
            self.rail.configure(fg_color="transparent")

        # progress bar visibility
        if item.status in (engine.CONVERTING, engine.SCANNING):
            self.progress.pack(anchor="w", pady=(6, 0))
            self.progress.set(item.progress)
        else:
            self.progress.pack_forget()

        # unlock affordance
        if item.status == engine.ENCRYPTED and item.password is None:
            self.unlock_btn.pack(side="left", padx=(8, 0))
        else:
            self.unlock_btn.pack_forget()

    def set_progress(self, value):
        self.item.progress = value
        if self.progress.winfo_ismapped():
            self.progress.set(value)

    def flash_done(self):
        if REDUCED_MOTION:
            return
        mode = ctk.get_appearance_mode().lower()
        self.configure(fg_color=theme.FLASH[mode])
        self.after(800, lambda: self.configure(fg_color=theme.BG))

    def set_selected(self, value):
        self.item.selected = value
        if value:
            self.check.select()
        else:
            self.check.deselect()

    def on_theme_change(self):
        self.dot._bg = theme.BG
        self.dot.on_theme_change()


def _pages_label(item: FileItem) -> str:
    if item.status == engine.ENCRYPTED:
        return f"{item.pages} pp" if item.pages else "—"
    return f"{item.pages} pp" if item.pages else "—"


# ---------------------------------------------------------------------------
# Password dialog
# ---------------------------------------------------------------------------
class PasswordDialog(ctk.CTkToplevel):
    def __init__(self, master, filename: str, fonts):
        super().__init__(master)
        self.result: str | None = None
        self.title("Unlock PDF")
        self.geometry("360x190")
        self.resizable(False, False)
        self.configure(fg_color=theme.BG)
        self.transient(master)
        ctk.CTkLabel(self, text="This PDF is password-protected",
                     font=fonts.heading, text_color=theme.TEXT).pack(anchor="w", padx=20, pady=(20, 2))
        ctk.CTkLabel(self, text=filename, font=fonts.mono, text_color=theme.MUTED).pack(anchor="w", padx=20)
        self.entry = ctk.CTkEntry(self, show="•", width=320, height=34,
                                  fg_color=theme.SURFACE, border_color=theme.BORDER,
                                  text_color=theme.TEXT, font=fonts.body)
        self.entry.pack(padx=20, pady=(14, 0))
        self.entry.focus_set()
        btns = ctk.CTkFrame(self, fg_color="transparent")
        btns.pack(fill="x", padx=20, pady=16)
        ctk.CTkButton(btns, text="Cancel", height=32, fg_color="transparent",
                      border_width=1, border_color=theme.BORDER, text_color=theme.TEXT,
                      hover_color=HOVER_WASH, font=fonts.control,
                      command=self._cancel).pack(side="right", padx=(8, 0))
        ctk.CTkButton(btns, text="Unlock", height=32, fg_color=theme.ACCENT,
                      hover_color=theme.ACCENT_HOVER, text_color="#fff",
                      font=fonts.control, command=self._ok).pack(side="right")
        self.entry.bind("<Return>", lambda _e: self._ok())
        self.bind("<Escape>", lambda _e: self._cancel())
        self.protocol("WM_DELETE_WINDOW", self._cancel)
        self.after(0, self._grab)

    def _grab(self):
        # grab_set fails until the window is viewable; wait then retry.
        if not self.winfo_exists():
            return
        try:
            self.wait_visibility()
            self.grab_set()
        except Exception:
            if self.winfo_exists():
                self.after(50, self._grab)

    def _ok(self):
        self.result = self.entry.get()
        self.destroy()

    def _cancel(self):
        self.result = None
        self.destroy()


# ---------------------------------------------------------------------------
# About dialog
# ---------------------------------------------------------------------------
class AboutDialog(ctk.CTkToplevel):
    def __init__(self, master, fonts):
        super().__init__(master)
        self.title("About PDF Converter")
        self.geometry("420x320")
        self.resizable(False, False)
        self.configure(fg_color=theme.BG)
        self.transient(master)

        header = ctk.CTkFrame(self, fg_color="transparent")
        header.pack(fill="x", padx=24, pady=(24, 8))
        brand = BrandTile(header, size=44, bg=theme.BG)
        brand.pack(side="left", padx=(0, 14))
        tcell = ctk.CTkFrame(header, fg_color="transparent")
        tcell.pack(side="left", anchor="w")
        ctk.CTkLabel(tcell, text="PDF → DOCX · Markdown", font=fonts.title,
                     text_color=theme.TEXT, anchor="w").pack(anchor="w")
        ctk.CTkLabel(tcell, text=f"Version {__version__}", font=fonts.small,
                     text_color=theme.MUTED, anchor="w").pack(anchor="w")

        ctk.CTkLabel(self, text="Convert PDFs to editable Word and Markdown files.",
                     font=fonts.body, text_color=theme.MUTED, wraplength=360,
                     justify="left", anchor="w").pack(fill="x", padx=24, pady=(4, 12))

        info = (f"{platform.system()} {platform.release()}  ·  "
                f"Python {sys.version_info.major}.{sys.version_info.minor}."
                f"{sys.version_info.micro}")
        ctk.CTkLabel(self, text=info, font=fonts.mono, text_color=theme.MUTED,
                     anchor="w").pack(fill="x", padx=24, pady=(0, 2))
        ctk.CTkLabel(self, text="Log: " + _display_dir(logsetup.LOG_PATH),
                     font=fonts.mono, text_color=theme.MUTED, anchor="w",
                     wraplength=360, justify="left").pack(fill="x", padx=24)

        btns = ctk.CTkFrame(self, fg_color="transparent")
        btns.pack(fill="x", padx=24, pady=20, side="bottom")
        ctk.CTkButton(btns, text="Close", height=32, fg_color=theme.ACCENT,
                      hover_color=theme.ACCENT_HOVER, text_color="#fff",
                      font=fonts.control, command=self.destroy).pack(side="right")
        ctk.CTkButton(btns, text="Open log folder", height=32, fg_color="transparent",
                      border_width=1, border_color=theme.BORDER, text_color=theme.TEXT,
                      hover_color=HOVER_WASH, font=fonts.control,
                      command=lambda: platform_utils.open_folder(logsetup.LOG_PATH)
                      ).pack(side="right", padx=(0, 8))

        self.bind("<Escape>", lambda _e: self.destroy())
        self.after(0, self._grab)

    def _grab(self):
        if not self.winfo_exists():
            return
        try:
            self.wait_visibility()
            self.grab_set()
        except Exception:
            if self.winfo_exists():
                self.after(50, self._grab)


# ---------------------------------------------------------------------------
# Settings drawer (in-window overlay)
# ---------------------------------------------------------------------------
class SettingsDrawer:
    WIDTH = 380

    def __init__(self, app: "App"):
        self.app = app
        self._alive = True
        self.scrim = ctk.CTkFrame(app, fg_color=("#475569", "#020509"), corner_radius=0)
        self.drawer = ctk.CTkFrame(app, fg_color=theme.SURFACE, corner_radius=0,
                                   border_width=1, border_color=theme.BORDER, width=self.WIDTH)
        self.drawer.pack_propagate(False)
        self._build()
        self.scrim.place(relx=0, rely=0, relwidth=1, relheight=1)
        self.scrim.bind("<Button-1>", lambda _e: self.close())
        app.bind("<Escape>", lambda _e: self.close())
        # slide in
        if REDUCED_MOTION:
            self._place_drawer(-self.WIDTH)
        else:
            self._x = 0
            self._place_drawer(0)
            self._animate_in()

    def _animate_in(self):
        if not self._alive or not self.drawer.winfo_exists():
            return
        self._x -= max(18, self.WIDTH // 12)
        if self._x <= -self.WIDTH:
            self._x = -self.WIDTH
            # Use place() (not place_configure): customtkinter DPI-scales the x
            # offset on place() to match the scaled drawer width, so the drawer's
            # right edge lands exactly on the window edge. place_configure() is
            # NOT scaled, which left the drawer overhanging the window on HiDPI.
            self._place_drawer(self._x)
            return
        self._place_drawer(self._x)
        self.app.after(12, self._animate_in)

    def _place_drawer(self, x):
        self.drawer.place(relx=1.0, x=x, rely=0, relheight=1)

    def _build(self):
        app = self.app
        f = app.fonts
        # header
        header = ctk.CTkFrame(self.drawer, fg_color=theme.SURFACE, height=52,
                              corner_radius=0)
        header.pack(fill="x")
        ctk.CTkLabel(header, text="Settings", font=f.heading,
                     text_color=theme.TEXT).pack(side="left", padx=20, pady=14)
        ctk.CTkButton(header, text="", width=30, height=30, corner_radius=7,
                      fg_color="transparent", hover_color=HOVER_WASH,
                      image=icon_image("x", 15, theme.MUTED[0], theme.MUTED[1]),
                      command=self.close).pack(side="right", padx=16)
        ctk.CTkFrame(self.drawer, height=1, fg_color=theme.BORDER).pack(fill="x")

        body = ctk.CTkScrollableFrame(self.drawer, fg_color=theme.SURFACE,
                                      label_text="")
        body.pack(fill="both", expand=True)

        cfg = app.cfg

        # Conversion — workers stepper
        self._section(body, "Conversion")
        wrow = ctk.CTkFrame(body, fg_color="transparent")
        wrow.pack(fill="x", padx=4, pady=(0, 4))
        ctk.CTkLabel(wrow, text="Parallel workers", font=f.body,
                     text_color=theme.TEXT).pack(side="left")
        stepper = ctk.CTkFrame(wrow, fg_color="transparent")
        stepper.pack(side="right")
        self.workers_var = ctk.StringVar(value=str(cfg["workers"]))
        ctk.CTkButton(stepper, text="−", width=30, height=28, corner_radius=6,
                      fg_color=theme.BG, hover_color=HOVER_WASH, text_color=theme.TEXT,
                      border_width=1, border_color=theme.BORDER, font=f.control,
                      command=lambda: self._step_workers(-1)).pack(side="left")
        ctk.CTkLabel(stepper, textvariable=self.workers_var, width=34,
                     font=f.body_med, text_color=theme.TEXT).pack(side="left", padx=4)
        ctk.CTkButton(stepper, text="+", width=30, height=28, corner_radius=6,
                      fg_color=theme.BG, hover_color=HOVER_WASH, text_color=theme.TEXT,
                      border_width=1, border_color=theme.BORDER, font=f.control,
                      command=lambda: self._step_workers(1)).pack(side="left")
        self._caption(body, "Caps concurrent conversions · default CPU − 1")
        self._rule(body)

        # Output filenames — prefix/suffix + preview + mirror
        self._section(body, "Output filenames")
        names = ctk.CTkFrame(body, fg_color="transparent")
        names.pack(fill="x", padx=4)
        self.prefix_var = ctk.StringVar(value=cfg["prefix"])
        self.suffix_var = ctk.StringVar(value=cfg["suffix"])
        self.prefix_var.trace_add("write", lambda *_: self._update_preview())
        self.suffix_var.trace_add("write", lambda *_: self._update_preview())
        pcol = ctk.CTkFrame(names, fg_color="transparent")
        pcol.pack(side="left", expand=True, fill="x", padx=(0, 6))
        ctk.CTkLabel(pcol, text="Prefix", font=f.caption, text_color=theme.MUTED).pack(anchor="w")
        ctk.CTkEntry(pcol, textvariable=self.prefix_var, height=30, fg_color=theme.BG,
                     border_color=theme.BORDER, text_color=theme.TEXT, font=f.body).pack(fill="x")
        scol = ctk.CTkFrame(names, fg_color="transparent")
        scol.pack(side="left", expand=True, fill="x", padx=(6, 0))
        ctk.CTkLabel(scol, text="Suffix", font=f.caption, text_color=theme.MUTED).pack(anchor="w")
        ctk.CTkEntry(scol, textvariable=self.suffix_var, height=30, fg_color=theme.BG,
                     border_color=theme.BORDER, text_color=theme.TEXT, font=f.body).pack(fill="x")
        self.preview_lbl = ctk.CTkLabel(body, text="", font=f.mono, text_color=theme.MUTED,
                                        anchor="w", justify="left")
        self.preview_lbl.pack(fill="x", padx=4, pady=(8, 4))
        self._update_preview()
        self.mirror_sw = self._switch(body, "Mirror source subfolders",
                                      "Recreate the folder tree under the output folder",
                                      cfg["mirror"])
        self._rule(body)

        # Notifications
        self._section(body, "Notifications")
        self.notify_sw = self._switch(body, "Notify when a batch completes",
                                      "Desktop notification on Windows, macOS & Linux",
                                      cfg["notify"])
        self._rule(body)

        # Audit log
        self._section(body, "Audit log")
        self._caption(body, "Every run is appended: timestamp, source, destination, status, duration.")
        arow = ctk.CTkFrame(body, fg_color="transparent")
        arow.pack(fill="x", padx=4, pady=(2, 4))
        ctk.CTkLabel(arow, text=_display_dir(audit.AUDIT_PATH.parent) + "/audit.csv",
                     font=f.mono, text_color=theme.MUTED).pack(side="left")
        ctk.CTkButton(arow, text="Open", width=60, height=28, corner_radius=6,
                      fg_color=theme.BG, hover_color=HOVER_WASH, text_color=theme.TEXT,
                      border_width=1, border_color=theme.BORDER, font=f.small,
                      command=lambda: platform_utils.open_folder(audit.AUDIT_PATH)).pack(side="right")
        self._rule(body)

        # General
        self._section(body, "General")
        self.remember_sw = self._switch(body, "Remember folders & preferences",
                                        "Persist settings between sessions", cfg["remember"])
        self._rule(body)

        # About
        self._section(body, "About")
        arow2 = ctk.CTkFrame(body, fg_color="transparent")
        arow2.pack(fill="x", padx=4, pady=(2, 4))
        ctk.CTkLabel(arow2, text=f"PDF Converter v{__version__}", font=f.body,
                     text_color=theme.TEXT).pack(side="left")
        ctk.CTkButton(arow2, text="About", width=70, height=28, corner_radius=6,
                      fg_color=theme.BG, hover_color=HOVER_WASH, text_color=theme.TEXT,
                      border_width=1, border_color=theme.BORDER, font=f.small,
                      command=self.app.open_about).pack(side="right")

        # footer
        ctk.CTkFrame(self.drawer, height=1, fg_color=theme.BORDER).pack(fill="x")
        footer = ctk.CTkFrame(self.drawer, fg_color=theme.SURFACE, height=56, corner_radius=0)
        footer.pack(fill="x")
        ctk.CTkButton(footer, text="Done", height=34, fg_color=theme.ACCENT,
                      hover_color=theme.ACCENT_HOVER, text_color="#fff", font=f.control,
                      command=self.close).pack(side="right", padx=20, pady=11)

    # -- builders -------------------------------------------------------
    def _section(self, parent, title):
        ctk.CTkLabel(parent, text=title.upper(), font=self.app.fonts.caption,
                     text_color=theme.MUTED, anchor="w").pack(fill="x", padx=4, pady=(14, 8))

    def _caption(self, parent, text):
        ctk.CTkLabel(parent, text=text, font=self.app.fonts.small, text_color=theme.MUTED,
                     anchor="w", justify="left", wraplength=320).pack(fill="x", padx=4, pady=(0, 4))

    def _rule(self, parent):
        ctk.CTkFrame(parent, height=1, fg_color=theme.BORDER_SOFT).pack(fill="x", pady=12)

    def _switch(self, parent, label, caption, value):
        row = ctk.CTkFrame(parent, fg_color="transparent")
        row.pack(fill="x", padx=4, pady=(0, 2))
        txt = ctk.CTkFrame(row, fg_color="transparent")
        txt.pack(side="left", fill="x", expand=True)
        ctk.CTkLabel(txt, text=label, font=self.app.fonts.body, text_color=theme.TEXT,
                     anchor="w").pack(fill="x")
        ctk.CTkLabel(txt, text=caption, font=self.app.fonts.small, text_color=theme.MUTED,
                     anchor="w", justify="left", wraplength=280).pack(fill="x")
        sw = ctk.CTkSwitch(row, text="", width=44, switch_width=34, switch_height=20,
                           progress_color=theme.ACCENT, fg_color=theme.BORDER,
                           button_color="#fff", button_hover_color="#fff")
        sw.pack(side="right")
        if value:
            sw.select()
        return sw

    def _step_workers(self, delta):
        try:
            v = int(self.workers_var.get())
        except ValueError:
            v = 1
        v = max(1, min(8, v + delta))
        self.workers_var.set(str(v))

    def _update_preview(self):
        pre, suf = self.prefix_var.get(), self.suffix_var.get()
        ext = ".docx" if self.app.cfg["format"] == "docx" else ".md"
        self.preview_lbl.configure(text=f"report.pdf  →  {pre}report{suf}{ext}")

    def close(self):
        if not self._alive:
            return
        self._alive = False
        cfg = self.app.cfg
        try:
            cfg["workers"] = max(1, min(8, int(self.workers_var.get())))
        except ValueError:
            pass
        cfg["prefix"] = self.prefix_var.get()
        cfg["suffix"] = self.suffix_var.get()
        cfg["mirror"] = bool(self.mirror_sw.get())
        cfg["notify"] = bool(self.notify_sw.get())
        cfg["remember"] = bool(self.remember_sw.get())
        try:
            self.app.unbind("<Escape>")
        except Exception:
            pass
        self.app.on_settings_closed()
        self.drawer.destroy()
        self.scrim.destroy()


# ---------------------------------------------------------------------------
# Main application window
# ---------------------------------------------------------------------------
class App(ctk.CTk):
    def __init__(self):
        super().__init__()
        # Route Tk callback exceptions (button handlers, after-jobs) to the log
        # and a friendly dialog rather than letting them vanish to stderr.
        self.report_callback_exception = self._on_tk_exception
        self.cfg = config.load()
        ctk.set_appearance_mode(self.cfg["theme"])
        self.title("PDF Converter")
        self._set_window_icon()
        self._fit_to_screen()
        self.configure(fg_color=theme.BG)

        self.fonts = theme.Fonts()
        self.items: list[FileItem] = []
        self._next_id = 0
        self._canvases: list = []
        self.event_queue: queue.Queue = queue.Queue()
        self.running = False
        self._closing = False
        self.cancel_event = threading.Event()
        self._mgr_thread: threading.Thread | None = None
        self.summary = {"ok": 0, "fail": 0, "skip": 0}
        self.run_total = 0
        self.run_completed = 0
        self.output_ready = False
        self.had_failures = False
        self.last_output_dir: Path | None = None
        self.audit_records: list[dict] = []
        self.log_open = False
        self.settings_drawer: SettingsDrawer | None = None
        engine.temp_sweep()  # reclaim temp files orphaned by a prior hard kill

        self._build_ui()
        self._enable_dnd()
        self._poll_events()
        self._animate()
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self._refresh_queue_visibility()
        self._update_convert_state()

    # -- icon helpers ---------------------------------------------------
    def _icon(self, name, size=15, kind="muted"):
        if kind == "muted":
            return icon_image(name, size, theme.MUTED[0], theme.MUTED[1])
        if kind == "white":
            return icon_image(name, size, "#ffffff", "#ffffff")
        if kind == "accent":
            return icon_image(name, size, theme.ACCENT, theme.ACCENT)
        if kind == "text":
            return icon_image(name, size, theme.TEXT[0], theme.TEXT[1])
        return icon_image(name, size, theme.MUTED[0], theme.MUTED[1])

    def _set_window_icon(self):
        """Set the title-bar / taskbar / dock icon, cross-platform & best-effort."""
        try:
            if sys.platform.startswith("win"):
                ico = platform_utils.asset_path("icon.ico")
                if ico.exists():
                    self.iconbitmap(default=str(ico))
                    return
            # macOS & Linux (and a Windows fallback): a PNG via iconphoto.
            png = platform_utils.asset_path("icon.png")
            if png.exists():
                import tkinter as tk

                # Keep a reference so Tk doesn't garbage-collect the image.
                self._icon_img = tk.PhotoImage(file=str(png))
                self.iconphoto(True, self._icon_img)
        except Exception as exc:
            log.debug("window icon not set: %s", exc)

    def _fit_to_screen(self, want_w: int = 900, want_h: int = 640):
        """Size and centre the window so it always fits the screen.

        customtkinter multiplies the window geometry by the display's DPI scale,
        so a fixed request (e.g. 900x640) can render far larger (1350x960 at
        150%) — bigger than a small or high-DPI laptop screen. That pushes the
        right-anchored settings drawer and the footer off-screen. Clamp the
        logical size to the available screen and pick a min size that also fits.
        """
        self.update_idletasks()
        try:
            scaling = float(ctk.ScalingTracker.get_window_scaling(self))
        except Exception:
            scaling = 1.0
        scaling = scaling or 1.0
        sw = self.winfo_screenwidth()
        sh = self.winfo_screenheight()
        # geometry() sizes are multiplied by `scaling` (positions are not), so
        # convert the physical screen budget — minus chrome/taskbar — to logical.
        max_w = max(480, int((sw - 24) / scaling))
        max_h = max(360, int((sh - 96) / scaling))
        w = min(want_w, max_w)
        h = min(want_h, max_h)
        # minsize is bounded by w/h (which already fit), so it can never exceed
        # the screen and the window can always be shown in full.
        self.minsize(min(560, w), min(420, h))
        px = max(0, (sw - int(w * scaling)) // 2)
        py = max(0, (sh - int(h * scaling)) // 2 - 24)
        self.geometry(f"{w}x{h}+{px}+{py}")

    def _on_tk_exception(self, exc_type, exc_value, exc_tb):
        """Tk callback-exception hook: log the traceback, show a friendly dialog."""
        log.critical("Tk callback exception", exc_info=(exc_type, exc_value, exc_tb))
        self._show_crash_dialog(exc_value)

    def _show_crash_dialog(self, exc):
        """Best-effort error dialog pointing the user at the log file."""
        try:
            if self._closing or not self.winfo_exists():
                return
            messagebox.showerror(
                "PDF Converter — Something went wrong",
                f"An unexpected error occurred:\n\n{type(exc).__name__}: {exc}\n\n"
                f"Details were saved to:\n{logsetup.LOG_PATH}",
            )
        except Exception:
            pass

    def register_canvas(self, widget):
        self._canvases.append(widget)

    def fmt_tag(self) -> str:
        return "DOCX" if self.cfg["format"] == "docx" else "MD"

    # ================================================================
    # UI construction
    # ================================================================
    def _build_ui(self):
        self._build_header()
        self._build_action_row()
        self._build_selection_bar()
        self._build_queue()
        self._build_options()
        self._build_footer()

    def _build_header(self):
        header = ctk.CTkFrame(self, fg_color=theme.BG, corner_radius=0, height=56)
        header.pack(fill="x")
        ctk.CTkFrame(self, height=1, fg_color=theme.BORDER_SOFT).pack(fill="x")
        brand = BrandTile(header, size=30, bg=theme.BG)
        brand.pack(side="left", padx=(20, 13), pady=13)
        self.register_canvas(brand)
        titlecell = ctk.CTkFrame(header, fg_color="transparent")
        titlecell.pack(side="left", pady=10)
        ctk.CTkLabel(titlecell, text="PDF → DOCX · Markdown", font=self.fonts.title,
                     text_color=theme.TEXT, anchor="w").pack(fill="x")
        ctk.CTkLabel(titlecell, text="Convert PDFs to editable documents",
                     font=self.fonts.small, text_color=theme.MUTED, anchor="w").pack(fill="x")

        right = ctk.CTkFrame(header, fg_color="transparent")
        right.pack(side="right", padx=20)
        ctk.CTkButton(right, text="", width=32, height=32, corner_radius=7,
                      fg_color="transparent", border_width=1, border_color=theme.BORDER,
                      hover_color=HOVER_WASH, image=self._icon("sliders", 16),
                      command=self.open_settings).pack(side="left", padx=(0, 8))
        self.theme_seg = SegmentedControl(
            right,
            options=[("dark", ""), ("light", "")],
            command=self._on_theme_select,
            value=self.cfg["theme"],
            icons={"dark": self._icon("moon", 14, "text"), "light": self._icon("sun", 14, "text")},
            seg_height=24,
        )
        self.theme_seg.pack(side="left")

    def _build_action_row(self):
        row = ctk.CTkFrame(self, fg_color=theme.BG, corner_radius=0)
        row.pack(fill="x")
        ctk.CTkFrame(self, height=1, fg_color=theme.BORDER_SOFT).pack(fill="x")
        inner = ctk.CTkFrame(row, fg_color="transparent")
        inner.pack(fill="x", padx=20, pady=12)

        self.convert_btn = ctk.CTkButton(
            inner, text="Convert", height=34, corner_radius=7, font=self.fonts.control,
            fg_color=theme.ACCENT, hover_color=theme.ACCENT_HOVER, text_color="#fff",
            image=self._icon("refresh", 15, "white"), command=self.start_convert,
        )
        self.convert_btn.pack(side="left", padx=(0, 8))
        ctk.CTkButton(inner, text="Add files", height=34, corner_radius=7, font=self.fonts.control,
                      fg_color="transparent", border_width=1, border_color=theme.BORDER,
                      text_color=theme.TEXT, hover_color=HOVER_WASH,
                      image=self._icon("plus", 15, "text"),
                      command=self.add_files).pack(side="left", padx=(0, 8))
        ctk.CTkButton(inner, text="Add folder", height=34, corner_radius=7, font=self.fonts.control,
                      fg_color="transparent", border_width=1, border_color=theme.BORDER,
                      text_color=theme.TEXT, hover_color=HOVER_WASH,
                      image=self._icon("folder", 15, "text"),
                      command=self.add_folder).pack(side="left", padx=(0, 8))
        ctk.CTkButton(inner, text="Clear", height=34, corner_radius=7, font=self.fonts.control,
                      fg_color="transparent", text_color=theme.MUTED, hover_color=HOVER_WASH,
                      command=self.clear_queue).pack(side="left")

        fmtcell = ctk.CTkFrame(inner, fg_color="transparent")
        fmtcell.pack(side="right")
        ctk.CTkLabel(fmtcell, text="FORMAT", font=self.fonts.caption,
                     text_color=theme.MUTED).pack(side="left", padx=(0, 8))
        self.format_seg = SegmentedControl(
            fmtcell, options=[("docx", "DOCX"), ("md", "Markdown")],
            command=self._on_format_select, value=self.cfg["format"], font=self.fonts.small,
        )
        self.format_seg.pack(side="left")

    def _build_selection_bar(self):
        self.sel_bar = ctk.CTkFrame(self, fg_color=theme.ACCENT_SOFT, corner_radius=0)
        self.sel_inner = ctk.CTkFrame(self.sel_bar, fg_color="transparent")
        self.sel_inner.pack(fill="x", padx=20, pady=8)
        self.sel_count_lbl = ctk.CTkLabel(self.sel_inner, text="", font=self.fonts.body_med,
                                          text_color=theme.TEXT)
        self.sel_count_lbl.pack(side="left", padx=(0, 12))
        ctk.CTkButton(self.sel_inner, text="Remove selected", fg_color="transparent",
                      text_color=theme.ST_FAIL, hover_color=HOVER_WASH, font=self.fonts.small,
                      width=0, command=self.remove_selected).pack(side="left", padx=(0, 8))
        ctk.CTkButton(self.sel_inner, text="Deselect all", fg_color="transparent",
                      text_color=theme.MUTED, hover_color=HOVER_WASH, font=self.fonts.small,
                      width=0, command=self.deselect_all).pack(side="left")
        # not packed until a selection exists

    def _build_queue(self):
        # sticky header row (outside the scroll area)
        self.qheader = ctk.CTkFrame(self, fg_color=theme.SURFACE, corner_radius=0)
        self.qheader_sep = ctk.CTkFrame(self, height=1, fg_color=theme.BORDER)
        hinner = ctk.CTkFrame(self.qheader, fg_color="transparent")
        hinner.pack(fill="x", padx=0, pady=9)
        _configure_columns(hinner)
        self.select_all = ctk.CTkCheckBox(
            hinner, text="", width=18, checkbox_width=17, checkbox_height=17,
            corner_radius=4, border_width=2, fg_color=theme.ACCENT,
            hover_color=theme.ACCENT_HOVER, border_color=theme.MUTED,
            command=self.toggle_select_all)
        self.select_all.grid(row=0, column=0, padx=(18, 0), sticky="w")
        for col, text in ((1, "FILE"), (2, "PAGES"), (3, "FORMAT"), (4, "STATUS")):
            ctk.CTkLabel(hinner, text=text, font=self.fonts.caption, text_color=theme.MUTED,
                         anchor="w").grid(row=0, column=col, sticky="w", padx=10)

        # The scrollable queue lives inside a plain wrapper frame so the sticky
        # header (and selection bar) can be (un)packed relative to a normal
        # widget — pack(before=...) cannot target a CTkScrollableFrame.
        self.qwrap = ctk.CTkFrame(self, fg_color=theme.BG, corner_radius=0)
        self.qwrap.pack(fill="both", expand=True)
        self.queue = ctk.CTkScrollableFrame(self.qwrap, fg_color=theme.BG, label_text="",
                                            corner_radius=0)
        self.queue.pack(fill="both", expand=True)

        # drop overlay (shown during a drag) — over the whole queue area
        self.drop_overlay = ctk.CTkFrame(self.qwrap, fg_color=theme.ACCENT_SOFT,
                                         border_width=2, border_color=theme.ACCENT, corner_radius=10)
        self.drop_label = ctk.CTkLabel(self.drop_overlay, text="Drop PDFs to add to the queue",
                                       font=self.fonts.body_med, text_color=theme.ACCENT)
        self.drop_label.place(relx=0.5, rely=0.5, anchor="center")

        # empty state
        self.empty_state = ctk.CTkFrame(self.qwrap, fg_color="transparent")
        es = self.empty_state
        tile = ctk.CTkFrame(es, width=62, height=62, fg_color="transparent",
                            border_width=2, border_color=theme.BORDER, corner_radius=14)
        tile.pack(pady=(0, 8))
        tile.pack_propagate(False)
        ctk.CTkLabel(tile, text="", image=self._icon("file-check", 26)).place(relx=0.5, rely=0.5, anchor="center")
        ctk.CTkLabel(es, text="No files in the queue", font=self.fonts.heading,
                     text_color=theme.TEXT).pack()
        ctk.CTkLabel(es, text="Add PDFs or drop a folder here to start converting to DOCX or Markdown.",
                     font=self.fonts.body, text_color=theme.MUTED, wraplength=300,
                     justify="center").pack(pady=(2, 14))
        ebtns = ctk.CTkFrame(es, fg_color="transparent")
        ebtns.pack()
        ctk.CTkButton(ebtns, text="Add files", height=34, corner_radius=7, font=self.fonts.control,
                      fg_color="transparent", border_width=1, border_color=theme.BORDER,
                      text_color=theme.TEXT, hover_color=HOVER_WASH,
                      image=self._icon("plus", 15, "text"),
                      command=self.add_files).pack(side="left", padx=4)
        ctk.CTkButton(ebtns, text="Add folder", height=34, corner_radius=7, font=self.fonts.control,
                      fg_color="transparent", border_width=1, border_color=theme.BORDER,
                      text_color=theme.TEXT, hover_color=HOVER_WASH,
                      image=self._icon("folder", 15, "text"),
                      command=self.add_folder).pack(side="left", padx=4)

    def _build_options(self):
        ctk.CTkFrame(self, height=1, fg_color=theme.BORDER_SOFT).pack(fill="x")
        strip = ctk.CTkFrame(self, fg_color=theme.SURFACE, corner_radius=0)
        strip.pack(fill="x")
        inner = ctk.CTkFrame(strip, fg_color="transparent")
        inner.pack(fill="x", padx=20, pady=12)

        # Output
        ocell = ctk.CTkFrame(inner, fg_color="transparent")
        ocell.pack(side="left")
        ctk.CTkLabel(ocell, text="OUTPUT", font=self.fonts.caption,
                     text_color=theme.MUTED).pack(side="left", padx=(0, 9))
        self.output_seg = SegmentedControl(
            ocell, options=[("next", "Next to source"), ("choose", "Choose folder…")],
            command=self._on_output_select, value=self.cfg["output_mode"],
            font=self.fonts.small, track_bg=theme.BG)
        self.output_seg.pack(side="left")
        self.path_chip = ctk.CTkLabel(ocell, text="", font=self.fonts.mono,
                                      text_color=theme.MUTED, fg_color=theme.BG,
                                      corner_radius=5, padx=7)
        self.mirror_note = ctk.CTkLabel(ocell, text="· mirroring subfolders",
                                        font=self.fonts.small, text_color=theme.ACCENT)

        self._divider(inner)

        # Pages
        pcell = ctk.CTkFrame(inner, fg_color="transparent")
        pcell.pack(side="left")
        ctk.CTkLabel(pcell, text="PAGES", font=self.fonts.caption,
                     text_color=theme.MUTED).pack(side="left", padx=(0, 9))
        self.start_var = ctk.StringVar()
        self.end_var = ctk.StringVar()
        self.start_var.trace_add("write", lambda *_: self._on_pages_changed())
        self.end_var.trace_add("write", lambda *_: self._on_pages_changed())
        self.start_entry = ctk.CTkEntry(pcell, textvariable=self.start_var, width=46, height=28,
                                        justify="center", fg_color=theme.BG, border_color=theme.BORDER,
                                        text_color=theme.TEXT, font=self.fonts.small,
                                        placeholder_text="0")
        self.start_entry.pack(side="left")
        ctk.CTkLabel(pcell, text="–", text_color=theme.MUTED).pack(side="left", padx=6)
        self.end_entry = ctk.CTkEntry(pcell, textvariable=self.end_var, width=46, height=28,
                                      justify="center", fg_color=theme.BG, border_color=theme.BORDER,
                                      text_color=theme.TEXT, font=self.fonts.small,
                                      placeholder_text="end")
        self.end_entry.pack(side="left")
        self.page_err = ctk.CTkLabel(pcell, text="start ≤ end", font=self.fonts.small,
                                     text_color=theme.ST_FAIL)

        self._divider(inner)

        self.overwrite_cb = ctk.CTkCheckBox(
            inner, text="Overwrite existing", font=self.fonts.small, text_color=theme.TEXT,
            checkbox_width=17, checkbox_height=17, corner_radius=4, border_width=2,
            fg_color=theme.ACCENT, hover_color=theme.ACCENT_HOVER, border_color=theme.MUTED,
            command=self._on_overwrite)
        self.overwrite_cb.pack(side="left")
        if self.cfg["overwrite"]:
            self.overwrite_cb.select()

        self._divider(inner)

        self.ocr_cb = ctk.CTkCheckBox(
            inner, text="OCR scanned PDFs", font=self.fonts.small, text_color=theme.TEXT,
            checkbox_width=17, checkbox_height=17, corner_radius=4, border_width=2,
            fg_color=theme.ACCENT, hover_color=theme.ACCENT_HOVER, border_color=theme.MUTED,
            command=self._on_ocr)
        self.ocr_cb.pack(side="left")
        if self.cfg["ocr"]:
            self.ocr_cb.select()

        self._sync_output_chip()

    def _divider(self, parent):
        ctk.CTkFrame(parent, width=1, height=22, fg_color=theme.BORDER_SOFT).pack(side="left", padx=14)

    def _build_footer(self):
        ctk.CTkFrame(self, height=1, fg_color=theme.BORDER_SOFT).pack(fill="x")
        footer = ctk.CTkFrame(self, fg_color=theme.SURFACE, corner_radius=0)
        footer.pack(fill="x")
        self.footer_inner = ctk.CTkFrame(footer, fg_color="transparent")
        self.footer_inner.pack(fill="x", padx=20, pady=14)

        # summary banner (created on demand)
        self.summary_banner = None

        prow = ctk.CTkFrame(self.footer_inner, fg_color="transparent")
        prow.pack(fill="x")
        self.overall_bar = ctk.CTkProgressBar(prow, height=8, corner_radius=999,
                                              fg_color=theme.INSET, progress_color=theme.ACCENT)
        self.overall_bar.pack(side="left", fill="x", expand=True)
        self.overall_bar.set(0)
        self.count_lbl = ctk.CTkLabel(prow, text="0 / 0 converted", font=self.fonts.body_med,
                                      text_color=theme.TEXT)
        self.count_lbl.pack(side="left", padx=(14, 0))
        self.status_word = ctk.CTkLabel(prow, text="Idle", font=self.fonts.small,
                                        text_color=theme.MUTED, width=84, anchor="e")
        self.status_word.pack(side="left", padx=(8, 0))

        brow = ctk.CTkFrame(self.footer_inner, fg_color="transparent")
        brow.pack(fill="x", pady=(13, 0))
        self.cancel_btn = ctk.CTkButton(brow, text="Cancel", height=30, corner_radius=7,
                                        font=self.fonts.small, fg_color="transparent",
                                        border_width=1, border_color=theme.BORDER,
                                        text_color=theme.TEXT, hover_color=HOVER_WASH,
                                        command=self.cancel_run)
        self.cancel_btn.pack(side="left", padx=(0, 8))
        self.retry_btn = ctk.CTkButton(brow, text="Retry failed", height=30, corner_radius=7,
                                       font=self.fonts.small, fg_color="transparent",
                                       border_width=1, border_color=theme.BORDER,
                                       text_color=theme.TEXT, hover_color=HOVER_WASH,
                                       image=self._icon("refresh", 14, "text"),
                                       command=self.retry_failed)
        self.retry_btn.pack(side="left", padx=(0, 8))
        self.open_btn = ctk.CTkButton(brow, text="Open output folder", height=30, corner_radius=7,
                                      font=self.fonts.small, fg_color="transparent",
                                      border_width=1, border_color=theme.BORDER,
                                      text_color=theme.TEXT, hover_color=HOVER_WASH,
                                      image=self._icon("folder-open", 14, "text"),
                                      command=self.open_output)
        self.open_btn.pack(side="left")
        self.log_btn = ctk.CTkButton(brow, text="Log", height=30, corner_radius=7,
                                     font=self.fonts.small, fg_color="transparent",
                                     text_color=theme.MUTED, hover_color=HOVER_WASH,
                                     image=self._icon("caret-right", 14), compound="left",
                                     command=self.toggle_log)
        self.log_btn.pack(side="right")

        self.log_frame = ctk.CTkScrollableFrame(self.footer_inner, fg_color=theme.INSET,
                                                label_text="", height=140, corner_radius=8)
        self.log_lines: list = []
        self._log_empty = ctk.CTkLabel(self.log_frame, text="No activity yet. Press Convert to begin.",
                                       font=self.fonts.mono, text_color=theme.MUTED, anchor="w")
        self._log_empty.pack(fill="x")

    # ================================================================
    # Queue management
    # ================================================================
    def add_files(self):
        initial = self.cfg.get("last_files_dir") or str(Path.home())
        paths = filedialog.askopenfilenames(
            title="Add PDF files", initialdir=initial,
            filetypes=[("PDF files", "*.pdf")])
        if paths:
            self.cfg["last_files_dir"] = str(Path(paths[0]).parent)
            self._add_paths([Path(p) for p in paths])

    def add_folder(self):
        initial = self.cfg.get("last_folder_dir") or str(Path.home())
        folder = filedialog.askdirectory(title="Add a folder of PDFs", initialdir=initial)
        if folder:
            self.cfg["last_folder_dir"] = folder
            found = engine.discover_pdfs(Path(folder), recursive=True)
            if not found:
                self.log(f"No PDFs found in {folder}", "warn")
            self._add_paths(found, mirror_root=Path(folder))

    def _add_paths(self, paths, mirror_root: Path | None = None):
        existing = {str(it.path) for it in self.items}
        new_items = []
        for p in paths:
            if p.suffix.lower() != ".pdf" or str(p) in existing:
                continue
            existing.add(str(p))
            item = FileItem(self._next_id, p, 0, engine.QUEUED, mirror_root=mirror_root)
            self._next_id += 1
            self.items.append(item)
            new_items.append(item)
        for item in new_items:
            row = FileRow(self.queue, self, item)
            row.pack(fill="x")
        if new_items:
            self.log(f"Added {len(new_items)} file(s).", "info")
            self._probe_async(new_items)
        self._refresh_queue_visibility()
        self._update_convert_state()

    def _probe_async(self, items):
        """Probe new files off-thread for pages / text-layer / encryption."""
        def work():
            for item in items:
                info = engine.probe_pdf(str(item.path))
                self.event_queue.put(("probe", item.id, info))
        threading.Thread(target=work, daemon=True).start()

    def remove_item(self, item: FileItem):
        if self.running:
            return
        if item.row:
            item.row.destroy()
        self.items.remove(item)
        self._refresh_queue_visibility()
        self.on_selection_changed()
        self._update_convert_state()

    def remove_selected(self):
        if self.running:
            return
        for item in [it for it in self.items if it.selected]:
            if item.row:
                item.row.destroy()
            self.items.remove(item)
        self._refresh_queue_visibility()
        self.on_selection_changed()
        self._update_convert_state()

    def clear_queue(self):
        if self.running:
            return
        for item in self.items:
            if item.row:
                item.row.destroy()
        self.items.clear()
        self._refresh_queue_visibility()
        self.on_selection_changed()
        self._update_convert_state()

    def toggle_select_all(self):
        value = bool(self.select_all.get())
        for item in self.items:
            if item.row:
                item.row.set_selected(value)
        self.on_selection_changed()

    def deselect_all(self):
        for item in self.items:
            if item.row:
                item.row.set_selected(False)
        self.select_all.deselect()
        self.on_selection_changed()

    def on_selection_changed(self):
        selected = [it for it in self.items if it.selected]
        if selected:
            anchor = self.qheader if self.qheader.winfo_ismapped() else self.qwrap
            self.sel_bar.pack(before=anchor, fill="x")
            self.sel_count_lbl.configure(text=f"{len(selected)} selected")
        else:
            self.sel_bar.pack_forget()
        if self.items and all(it.selected for it in self.items):
            self.select_all.select()
        elif not selected:
            self.select_all.deselect()

    def _refresh_queue_visibility(self):
        if self.items:
            self.empty_state.place_forget()
            if not self.qheader.winfo_ismapped():
                # place header + separator right above the queue wrapper
                self.qheader.pack(fill="x", before=self.qwrap)
                self.qheader_sep.pack(fill="x", before=self.qwrap)
        else:
            self.qheader.pack_forget()
            self.qheader_sep.pack_forget()
            self.empty_state.place(relx=0.5, rely=0.5, anchor="center")

    # ================================================================
    # Options handlers
    # ================================================================
    def _on_format_select(self, val):
        self.cfg["format"] = val
        for item in self.items:
            if item.row:
                item.row.refresh()

    def _on_output_select(self, val):
        if val == "choose" and not self.cfg.get("output_dir"):
            folder = filedialog.askdirectory(title="Choose output folder")
            if not folder:
                self.output_seg.set("next")
                return
            self.cfg["output_dir"] = folder
        self.cfg["output_mode"] = val
        self._sync_output_chip()

    def _sync_output_chip(self):
        if self.cfg["output_mode"] == "choose" and self.cfg.get("output_dir"):
            self.path_chip.configure(text=_display_dir(Path(self.cfg["output_dir"])))
            self.path_chip.pack(side="left", padx=(8, 0))
            if self.cfg.get("mirror"):
                self.mirror_note.pack(side="left", padx=(6, 0))
            else:
                self.mirror_note.pack_forget()
        else:
            self.path_chip.pack_forget()
            self.mirror_note.pack_forget()

    def _on_overwrite(self):
        self.cfg["overwrite"] = bool(self.overwrite_cb.get())

    def _on_ocr(self):
        self.cfg["ocr"] = bool(self.ocr_cb.get())

    def _on_pages_changed(self):
        _start, _end, valid = self._parse_pages()
        border = theme.ST_FAIL if not valid else theme.BORDER
        self.start_entry.configure(border_color=border)
        self.end_entry.configure(border_color=border)
        if not valid:
            self.page_err.pack(side="left", padx=(8, 0))
        else:
            self.page_err.pack_forget()
        self._update_convert_state()

    def _parse_pages(self):
        """Return (start, end, valid)."""
        s_raw, e_raw = self.start_var.get().strip(), self.end_var.get().strip()
        start = end = None
        try:
            if s_raw:
                start = int(s_raw)
                if start < 0:
                    return None, None, False
            if e_raw:
                end = int(e_raw)
                if end < 0:
                    return None, None, False
        except ValueError:
            return None, None, False
        if start is not None and end is not None and start > end:
            return start, end, False
        return start, end, True

    # ================================================================
    # Theme / settings
    # ================================================================
    def _on_theme_select(self, val):
        self.cfg["theme"] = val
        ctk.set_appearance_mode(val)
        for c in self._canvases:
            try:
                c.on_theme_change()
            except Exception:
                pass

    def open_settings(self):
        if self.settings_drawer is None:
            self.settings_drawer = SettingsDrawer(self)

    def on_settings_closed(self):
        self.settings_drawer = None
        self._sync_output_chip()

    def open_about(self):
        AboutDialog(self, self.fonts)

    # ================================================================
    # Conversion run
    # ================================================================
    def start_convert(self):
        if self.running:
            return
        eligible = [it for it in self.items
                    if it.status in (engine.QUEUED, engine.DONE, engine.FAILED, engine.NOTEXT, engine.ENCRYPTED)]
        self._start_run(eligible)

    def retry_failed(self):
        if self.running:
            return
        failed = [it for it in self.items if it.status == engine.FAILED]
        if not failed:
            self.log("No failed files to retry.", "warn")
            return
        self._start_run(failed)

    def unlock_item(self, item: FileItem):
        if self.running or getattr(self, "_unlock_open", False):
            return  # avoid a second stacked password dialog
        self._unlock_open = True
        try:
            dlg = PasswordDialog(self, item.name, self.fonts)
            self.wait_window(dlg)
        finally:
            self._unlock_open = False
        if dlg.result is None:
            return
        item.password = dlg.result
        item.status = engine.QUEUED
        if item.row:
            item.row.refresh()
        self.log(f"Unlocked {item.name}.", "ok")
        if not self.running:
            self._start_run([item])

    def _start_run(self, candidates):
        _start, _end, valid = self._parse_pages()
        if not valid:
            self.log("Fix the page range before converting.", "error")
            return
        if not candidates:
            return

        # Reset the run counters up front so an all-skipped run can't show a
        # stale progress bar / count from a previous run.
        self.run_total = 0
        self.run_completed = 0
        self.count_lbl.configure(text="0 / 0 converted")
        self.overall_bar.set(0)

        out_mode = self.cfg["output_mode"]
        out_dir = Path(self.cfg["output_dir"]) if self.cfg.get("output_dir") else None
        mirror_on = self.cfg.get("mirror")
        fmt = self.cfg["format"]

        tasks = []
        pre_skipped = 0
        self.audit_records = []
        for item in candidates:
            # classify skips
            if item.status == engine.NOTEXT and not self.cfg["ocr"]:
                pre_skipped += 1
                self.audit_records.append({"source": str(item.path), "destination": "",
                                           "status": "skipped-notext", "duration": 0.0})
                self.log(f"Skipped {item.name}: no text layer (enable OCR).", "warn")
                continue
            if item.status == engine.ENCRYPTED and item.password is None:
                pre_skipped += 1
                self.audit_records.append({"source": str(item.path), "destination": "",
                                           "status": "skipped-encrypted", "duration": 0.0})
                self.log(f"Skipped {item.name}: encrypted (use Unlock).", "warn")
                continue
            # Per-item mirror root: each item remembers the folder it was added
            # under, so mixing files + multiple folders mirrors each correctly.
            item_mirror = item.mirror_root if mirror_on else None
            dst = engine.resolve_output_path(
                item.path, fmt, out_mode, out_dir, mirror_root=item_mirror,
                prefix=self.cfg["prefix"], suffix=self.cfg["suffix"],
                overwrite=self.cfg["overwrite"])
            tasks.append({
                "id": item.id, "src": str(item.path), "dst": str(dst), "fmt": fmt,
                "start": _start, "end": _end, "overwrite": self.cfg["overwrite"],
                "ocr": self.cfg["ocr"], "password": item.password,
            })
            item.status = engine.QUEUED
            item.progress = 0.0
            if item.row:
                item.row.refresh()
            self.last_output_dir = Path(dst).parent

        if not tasks:
            # everything was skipped
            self.summary = {"ok": 0, "fail": 0, "skip": pre_skipped}
            self._finish_run(cancelled=False)
            return

        self.running = True
        self.cancel_event.clear()
        self.summary = {"ok": 0, "fail": 0, "skip": pre_skipped}
        self.run_total = len(tasks)
        self.run_completed = 0
        self.had_failures = False
        self.output_ready = False
        self._task_by_id = {t["id"]: t for t in tasks}
        workers = max(1, min(int(self.cfg["workers"]), len(tasks)))
        self.log(f"Converting {len(tasks)} file(s) to {fmt.upper()} with {workers} worker(s)…", "info")
        self._set_running_ui(True)

        t = threading.Thread(target=self._run_manager, args=(tasks, workers), daemon=True)
        self._mgr_thread = t
        t.start()

    def _run_manager(self, tasks, workers):
        """Background thread: drives the process pool, posts events. No Tk here."""
        q = self.event_queue
        # Force 'spawn' on every OS: the GUI is multi-threaded, and forking a
        # threaded process (the Linux default) risks deadlocks. spawn is already
        # the Windows/macOS default, so this just makes Linux behave the same.
        mp_ctx = multiprocessing.get_context("spawn")
        try:
            with ProcessPoolExecutor(max_workers=workers, mp_context=mp_ctx) as ex:
                fut_to_task = {}
                order = []
                for t in tasks:
                    f = ex.submit(engine.convert_one, t)
                    fut_to_task[f] = t
                    order.append(f)
                remaining = list(order)
                emitted = set()
                cancelled = False
                while remaining:
                    run_now = [f for f in remaining if not f.done()][:workers]
                    for f in run_now:
                        tid = fut_to_task[f]["id"]
                        if tid not in emitted:
                            emitted.add(tid)
                            q.put(("converting", tid))
                    done, _ = wait(remaining, timeout=0.12, return_when=FIRST_COMPLETED)
                    for f in done:
                        remaining.remove(f)
                        task = fut_to_task[f]
                        if f.cancelled():
                            q.put(("revert", task["id"]))
                            continue
                        try:
                            res = f.result()
                        except Exception as exc:  # pragma: no cover
                            res = {"id": task["id"], "status": engine.FAILED,
                                   "message": str(exc), "duration": 0.0, "dst": task["dst"]}
                        q.put(("result", res))
                    if self.cancel_event.is_set() and not cancelled:
                        cancelled = True
                        for f in list(remaining):
                            if f.cancel():
                                remaining.remove(f)
                                q.put(("revert", fut_to_task[f]["id"]))
                        q.put(("log", "Cancelling… finishing in-flight file(s).", "warn"))
                q.put(("done_run", cancelled))
        except Exception as exc:  # pragma: no cover
            q.put(("log", f"Run error: {exc}", "error"))
            q.put(("done_run", False))

    def cancel_run(self):
        if self.running:
            self.cancel_event.set()
            self.status_word.configure(text="Cancelling")

    # ================================================================
    # Event loop (main thread)
    # ================================================================
    def _poll_events(self):
        if self._closing:
            return
        try:
            while True:
                evt = self.event_queue.get_nowait()
                # Isolate each event so one bad event can't kill the pump.
                try:
                    self._handle_event(evt)
                except Exception as exc:  # noqa: BLE001
                    try:
                        self.log(f"Internal event error: {exc}", "error")
                    except Exception:
                        pass
        except queue.Empty:
            pass
        finally:
            if not self._closing:
                self.after(40, self._poll_events)

    def _handle_event(self, evt):
        kind = evt[0]
        if kind == "probe":
            _, fid, info = evt
            item = self._item(fid)
            if not item:
                return
            item.pages = info.pages
            if info.error:
                item.status = engine.FAILED
                item.message = info.error
            elif info.encrypted:
                item.status = engine.ENCRYPTED
            elif not info.has_text:
                item.status = engine.NOTEXT
            else:
                item.status = engine.QUEUED
            if item.row:
                item.row.refresh()
        elif kind == "converting":
            item = self._item(evt[1])
            if item and item.status not in (engine.DONE,):
                item.status = engine.CONVERTING
                item.progress = max(item.progress, 0.04)
                if item.row:
                    item.row.refresh()
        elif kind == "revert":
            item = self._item(evt[1])
            if item:
                item.status = engine.QUEUED
                item.progress = 0.0
                if item.row:
                    item.row.refresh()
        elif kind == "result":
            self._apply_result(evt[1])
        elif kind == "done_run":
            self._finish_run(cancelled=evt[1])
        elif kind == "log":
            self.log(evt[1], evt[2] if len(evt) > 2 else "info")
        elif kind == "crash":
            # Posted by the global excepthook from a worker thread; we are now on
            # the main thread, so it's safe to show the dialog.
            self._show_crash_dialog(evt[1])

    def _apply_result(self, res):
        item = self._item(res["id"])
        self.run_completed += 1
        status = res["status"]
        dst = res.get("dst", "")
        if item:
            item.status = status
            item.message = res.get("message", "")
            if status == engine.DONE:
                item.progress = 1.0
                if item.row:
                    item.row.refresh()
                    item.row.flash_done()
            else:
                item.progress = 0.0
                if item.row:
                    item.row.refresh()
        # tally
        if status == engine.DONE:
            self.summary["ok"] += 1
            self.log(f"✓ {Path(res['dst']).name}", "ok")
        elif status in (engine.NOTEXT, engine.ENCRYPTED):
            self.summary["skip"] += 1
            self.log(f"Skipped {item.name if item else res['id']}: {res.get('message','')}", "warn")
        else:
            self.summary["fail"] += 1
            self.had_failures = True
            self.log(f"✗ {item.name if item else res['id']}: {res.get('message','')}", "error")
        self.audit_records.append({
            "source": str(item.path) if item else "", "destination": dst,
            "status": status, "duration": res.get("duration", 0.0)})
        self._recompute_progress()

    def _finish_run(self, cancelled):
        self.running = False
        self._set_running_ui(False)
        self.output_ready = self.summary["ok"] > 0
        log.info("Run finished: %d ok, %d failed, %d skipped (cancelled=%s)",
                 self.summary["ok"], self.summary["fail"], self.summary["skip"], cancelled)
        # audit
        audit.append_records(self.audit_records)
        # summary banner
        self._show_summary_banner()
        if cancelled:
            self.status_word.configure(text="Cancelled")
            self.log("Run cancelled.", "warn")
        else:
            self.status_word.configure(text="Complete")
            self.overall_bar.set(1.0 if self.run_total else 0)
            self.log(
                f"Done: {self.summary['ok']} succeeded · {self.summary['fail']} failed "
                f"· {self.summary['skip']} skipped", "info")
            if self.cfg.get("notify"):
                platform_utils.notify(
                    "PDF Converter",
                    f"{self.summary['ok']} succeeded, {self.summary['fail']} failed, "
                    f"{self.summary['skip']} skipped.")
        self._update_convert_state()

    def _show_summary_banner(self):
        if self.summary_banner is not None:
            self.summary_banner.destroy()
        banner = ctk.CTkFrame(self.footer_inner, fg_color=theme.BG, corner_radius=9,
                              border_width=1, border_color=theme.BORDER)
        banner.pack(fill="x", pady=(0, 13), before=self.footer_inner.winfo_children()[0])
        tile = ctk.CTkLabel(banner, text="", image=self._icon("check", 15, "accent"),
                            fg_color=theme.ACCENT_SOFT, corner_radius=13, width=26, height=26)
        tile.pack(side="left", padx=(13, 12), pady=10)
        s = self.summary
        # Compose from adjacent labels so each count keeps its status colour
        # (the signature colour semantics from the handoff).
        segs = [
            ("Conversion complete.", theme.TEXT, self.fonts.body_med),
            (f"  {s['ok']} succeeded", theme.ST_DONE, self.fonts.body),
            (" · ", theme.MUTED, self.fonts.body),
            (f"{s['fail']} failed", theme.ST_FAIL, self.fonts.body),
            (" · ", theme.MUTED, self.fonts.body),
            (f"{s['skip']} skipped", theme.ST_CONV, self.fonts.body),
        ]
        for text, color, font in segs:
            ctk.CTkLabel(banner, text=text, text_color=color, font=font).pack(side="left", pady=10)
        self.summary_banner = banner

    def _recompute_progress(self):
        if not self.run_total:
            return
        inflight = sum(min(it.progress, 0.97) for it in self.items
                       if it.status in (engine.CONVERTING, engine.SCANNING))
        frac = (self.run_completed + inflight) / self.run_total
        self.overall_bar.set(min(1.0, frac))
        self.count_lbl.configure(text=f"{self.run_completed} / {self.run_total} converted")

    # ================================================================
    # Animation tick — eases per-file converting bars
    # ================================================================
    def _animate(self):
        if self._closing:
            return
        if self.running and not REDUCED_MOTION:
            for item in self.items:
                if item.status in (engine.CONVERTING, engine.SCANNING):
                    item.progress += (0.95 - item.progress) * 0.05
                    if item.row:
                        item.row.set_progress(item.progress)
            self._recompute_progress()
            self._spin_convert_btn()
        self.after(90, self._animate)

    def _spin_convert_btn(self):
        """Rotate the Convert button glyph while running (0.7s linear)."""
        if REDUCED_MOTION:
            return
        self._spin_angle = (getattr(self, "_spin_angle", 0) + 51) % 360  # ~0.7s/rev at 90ms
        img = icon_image(f"refresh@{self._spin_angle}", 15, "#ffffff", "#ffffff")
        if img is not None:
            self.convert_btn.configure(image=img)

    # ================================================================
    # Log
    # ================================================================
    _LOG_COLORS = {"ok": theme.ST_DONE, "error": theme.ST_FAIL,
                   "warn": theme.ST_CONV, "info": theme.MUTED}

    def log(self, text, level="info"):
        if self._closing:
            return
        ts = datetime.now().strftime("%H:%M:%S")
        if self._log_empty is not None:
            self._log_empty.destroy()
            self._log_empty = None
        lbl = ctk.CTkLabel(self.log_frame, text=f"[{ts}] {text}", anchor="w",
                           justify="left", font=self.fonts.mono,
                           text_color=self._LOG_COLORS.get(level, theme.MUTED),
                           wraplength=820)
        lbl.pack(fill="x")
        self.log_lines.append(lbl)
        if self.log_open:
            self.after(10, self._scroll_log_end)

    def _scroll_log_end(self):
        """Scroll the log to the bottom, tolerating teardown / CTk internals."""
        if self._closing:
            return
        try:
            self.log_frame._parent_canvas.yview_moveto(1.0)
        except Exception:
            pass  # private CTk attr or destroyed widget — auto-scroll is non-essential

    def toggle_log(self):
        self.log_open = not self.log_open
        if self.log_open:
            self.log_frame.pack(fill="x", pady=(12, 0))
            self.log_btn.configure(image=self._icon("caret-down", 14))
            self.after(20, self._scroll_log_end)
        else:
            self.log_frame.pack_forget()
            self.log_btn.configure(image=self._icon("caret-right", 14))

    # ================================================================
    # Button state
    # ================================================================
    def _update_convert_state(self):
        _s, _e, valid = self._parse_pages()
        can_convert = bool(self.items) and not self.running and valid
        self.convert_btn.configure(state="normal" if can_convert else "disabled")
        self.cancel_btn.configure(state="normal" if self.running else "disabled")
        has_failed = any(it.status == engine.FAILED for it in self.items)
        self.retry_btn.configure(state="normal" if (has_failed and not self.running) else "disabled")
        self.open_btn.configure(state="normal" if (self.output_ready and not self.running) else "disabled")

    def _set_running_ui(self, running):
        if running:
            self.convert_btn.configure(text="Converting…", state="disabled")
            self.status_word.configure(text="Converting")
            self.count_lbl.configure(text=f"0 / {self.run_total} converted")
            self.overall_bar.set(0)
        else:
            # Restore the static (non-rotated) Convert glyph.
            self.convert_btn.configure(text="Convert", image=self._icon("refresh", 15, "white"))
        self._update_convert_state()

    # ================================================================
    # Misc
    # ================================================================
    def open_output(self):
        target = self.last_output_dir or Path.home()
        if not platform_utils.open_folder(target):
            self.log(f"Could not open {target}", "error")

    def _item(self, fid):
        for it in self.items:
            if it.id == fid:
                return it
        return None

    # -- drag & drop (optional) ----------------------------------------
    def _enable_dnd(self):
        try:
            from tkinterdnd2 import DND_FILES, TkinterDnD  # noqa
            self.TkdndVersion = TkinterDnD._require(self)
            self.drop_target_register(DND_FILES)
            self.dnd_bind("<<Drop>>", self._on_drop)
            self.dnd_bind("<<DropEnter>>", lambda _e: self._show_drop_overlay(True))
            self.dnd_bind("<<DropLeave>>", lambda _e: self._show_drop_overlay(False))
        except Exception:
            pass  # P2 — degrade silently if tkinterdnd2 isn't available

    def _show_drop_overlay(self, show):
        if show:
            self.drop_overlay.place(relx=0, rely=0, relwidth=1, relheight=1)
        else:
            self.drop_overlay.place_forget()

    def _on_drop(self, event):
        self._show_drop_overlay(False)
        try:
            paths = self.tk.splitlist(event.data)
        except Exception:
            paths = []
        collected = []
        for p in paths:
            path = Path(p)
            if path.is_dir():
                collected.extend(engine.discover_pdfs(path, recursive=True))
            elif path.suffix.lower() == ".pdf":
                collected.append(path)
        if collected:
            self._add_paths(collected)

    def _on_close(self):
        self._closing = True
        if self.cfg.get("remember"):
            config.save(self.cfg)
        if self.running:
            # Stop submitting, let in-flight files finish, and don't lose the
            # audit trail for the partial run.
            self.cancel_event.set()
            if self._mgr_thread is not None:
                self._mgr_thread.join(timeout=10)
            try:
                audit.append_records(self.audit_records)
            except Exception:
                pass
        try:
            self.destroy()
        except Exception:
            pass


def main():
    multiprocessing.freeze_support()
    logsetup.setup_logging()
    app = App()

    def _on_crash(exc):
        # An excepthook may fire from a worker thread, and Tk is not thread-safe.
        # Hand off via the thread-safe event queue; the main-thread pump shows it.
        try:
            app.event_queue.put(("crash", exc))
        except Exception:
            pass

    logsetup.install_excepthook(on_crash=_on_crash)
    log.info("PDF Converter v%s starting (%s)", __version__, sys.platform)
    app.mainloop()
