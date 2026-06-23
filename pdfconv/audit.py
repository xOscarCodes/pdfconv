"""Persistent audit log (FR-23).

Appends one CSV record per converted/attempted file to
``~/.pdfconverter/audit.csv``: timestamp, source, destination, status,
duration (seconds). Writing is best-effort and never interrupts a run.
"""
from __future__ import annotations

import csv
from datetime import datetime
from pathlib import Path

from .config import APP_DIR

AUDIT_PATH = APP_DIR / "audit.csv"
_HEADER = ["timestamp", "source", "destination", "status", "duration_s"]


def append_records(records: list[dict]) -> None:
    """Append *records* (each: source, destination, status, duration) to the CSV."""
    if not records:
        return
    try:
        APP_DIR.mkdir(parents=True, exist_ok=True)
        new_file = not AUDIT_PATH.exists()
        with AUDIT_PATH.open("a", newline="", encoding="utf-8") as fh:
            writer = csv.writer(fh)
            if new_file:
                writer.writerow(_HEADER)
            now = datetime.now().isoformat(timespec="seconds")
            for rec in records:
                writer.writerow([
                    now,
                    rec.get("source", ""),
                    rec.get("destination", ""),
                    rec.get("status", ""),
                    f"{rec.get('duration', 0.0):.2f}",
                ])
    except Exception:
        pass
