"""Settings persistence (FR-25).

A small JSON config under ``~/.pdfconverter/config.json``. Loading is always
safe (missing/corrupt file -> defaults). Settings are only written to disk when
the user has "Remember folders & preferences" enabled.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

APP_DIR = Path.home() / ".pdfconverter"
CONFIG_PATH = APP_DIR / "config.json"

DEFAULTS: dict = {
    "theme": "dark",
    "format": "docx",          # 'docx' | 'md'
    "output_mode": "next",     # 'next' | 'choose'
    "output_dir": "",
    "overwrite": False,
    "ocr": False,
    "workers": max(1, (os.cpu_count() or 2) - 1),
    "prefix": "",
    "suffix": "",
    "mirror": False,
    "notify": False,
    "remember": False,
    "last_files_dir": "",
    "last_folder_dir": "",
}


def load() -> dict:
    """Return saved settings merged over defaults. Never raises."""
    cfg = dict(DEFAULTS)
    try:
        if CONFIG_PATH.exists():
            data = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                for key in DEFAULTS:
                    if key in data:
                        cfg[key] = data[key]
    except Exception:
        pass  # corrupt config -> fall back to defaults
    # Clamp workers to a sane range regardless of what was on disk.
    try:
        cfg["workers"] = max(1, min(8, int(cfg["workers"])))
    except (TypeError, ValueError):
        cfg["workers"] = DEFAULTS["workers"]
    return cfg


def save(cfg: dict) -> None:
    """Persist *cfg* to disk. Best-effort; failures are swallowed."""
    try:
        APP_DIR.mkdir(parents=True, exist_ok=True)
        data = {key: cfg.get(key, DEFAULTS[key]) for key in DEFAULTS}
        CONFIG_PATH.write_text(json.dumps(data, indent=2), encoding="utf-8")
    except Exception:
        pass
