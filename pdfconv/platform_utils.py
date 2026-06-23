"""Small OS-branching helpers (Windows, macOS & Linux).

Kept isolated so the rest of the app never hardcodes platform behaviour.
"""
from __future__ import annotations

import logging
import os
import shutil
import subprocess
import sys
from pathlib import Path

log = logging.getLogger("pdfconv")

# Bundled assets (icons) live inside the package so they ship with a source
# checkout, a ``pip install`` and a frozen build alike.
_PKG_DIR = Path(__file__).resolve().parent
ASSETS_DIR = _PKG_DIR / "assets"


def asset_path(name: str) -> Path:
    """Return the absolute path to a bundled asset, frozen-build aware.

    Falls back through the locations PyInstaller may extract data to
    (``sys._MEIPASS``); returns the in-package path if nothing exists yet.
    """
    candidates = [ASSETS_DIR / name]
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        candidates.append(Path(meipass) / "pdfconv" / "assets" / name)
        candidates.append(Path(meipass) / "assets" / name)
    for c in candidates:
        if c.exists():
            return c
    return candidates[0]


def open_folder(path: Path) -> bool:
    """Open *path* in the system file manager. Returns True on success.

    Windows -> Explorer (``os.startfile``); macOS -> ``open``; Linux -> ``xdg-open``.
    """
    path = Path(path)
    target = str(path if path.is_dir() else path.parent)
    try:
        if sys.platform.startswith("win"):
            os.startfile(target)  # type: ignore[attr-defined]  # noqa: S606
            return True
        if sys.platform == "darwin":
            subprocess.Popen(["open", target])
            return True
        # Linux / other POSIX
        if shutil.which("xdg-open"):
            subprocess.Popen(["xdg-open", target])
            return True
    except Exception as exc:
        log.debug("open_folder failed for %s: %s", target, exc)
    return False


def notify(title: str, message: str) -> None:
    """Best-effort desktop notification (FR-27). Degrades silently per-OS."""
    try:
        if sys.platform.startswith("win"):
            _notify_windows(title, message)
        elif sys.platform == "darwin":
            _notify_macos(title, message)
        elif shutil.which("notify-send"):
            subprocess.Popen(["notify-send", title, message])
    except Exception as exc:
        log.debug("notify failed: %s", exc)


def _notify_macos(title: str, message: str) -> None:
    """macOS notification via ``osascript`` (ships with every macOS).

    Best-effort: no-ops if osascript is somehow unavailable. Notification
    Center delivery is up to the OS / user permissions.
    """
    if shutil.which("osascript") is None:
        return
    script = (
        f'display notification "{_esc_applescript(message)}" '
        f'with title "{_esc_applescript(title)}"'
    )
    subprocess.Popen(
        ["osascript", "-e", script],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def _notify_windows(title: str, message: str) -> None:
    """Windows toast via PowerShell — no third-party dependency required.

    Best-effort (FR-27): toast delivery from a non-packaged app depends on the
    environment, so this no-ops silently if PowerShell isn't found or the call
    fails. powershell.exe ships with Windows, so the guard rarely trips.
    """
    if shutil.which("powershell") is None:
        return
    ps = (
        "[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, "
        "ContentType = WindowsRuntime] > $null; "
        "$t = [Windows.UI.Notifications.ToastNotificationManager]::GetTemplateContent("
        "[Windows.UI.Notifications.ToastTemplateType]::ToastText02); "
        f"$t.GetElementsByTagName('text').Item(0).AppendChild($t.CreateTextNode('{_esc(title)}')) > $null; "
        f"$t.GetElementsByTagName('text').Item(1).AppendChild($t.CreateTextNode('{_esc(message)}')) > $null; "
        "$n = [Windows.UI.Notifications.ToastNotification]::new($t); "
        "[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier('PDF Converter').Show($n);"
    )
    subprocess.Popen(
        ["powershell", "-NoProfile", "-WindowStyle", "Hidden", "-Command", ps],
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )


def _esc(text: str) -> str:
    """Escape a string for a single-quoted PowerShell literal."""
    return text.replace("'", "''")


def _esc_applescript(text: str) -> str:
    """Escape a string for a double-quoted AppleScript literal.

    Besides ``\\`` and ``"``, a raw newline/CR/tab would terminate the string
    literal and make osascript fail silently, so encode them as escapes too.
    """
    return (
        text.replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("\n", "\\n")
        .replace("\r", "\\r")
        .replace("\t", "\\t")
    )
