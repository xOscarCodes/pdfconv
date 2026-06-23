#!/usr/bin/env python3
"""PDF -> DOCX / Markdown converter — unified GUI + CLI entry point.

Run with no arguments to launch the desktop GUI; pass ``--input`` (and friends)
to run the headless CLI. Both share the same conversion engine.

    python pdf2docx_app.py                       # GUI
    python pdf2docx_app.py --input a.pdf --output out/   # CLI

The ``multiprocessing.freeze_support()`` call and the ``__main__`` guard are
required so the process pool works under ``spawn`` (Windows) and in PyInstaller
frozen builds.
"""
from __future__ import annotations

import multiprocessing
import sys


def _attach_parent_console() -> None:
    """Make CLI output visible from a windowed (console=False) frozen Windows build.

    A PyInstaller windowed EXE has no stdout/stderr, so CLI prints would vanish.
    When launched from a terminal we attach to the parent console and reopen the
    std streams onto it. No-op when not frozen, not on Windows, or no parent
    console exists. The GUI path never calls this, so GUI users see no console.
    """
    if not (sys.platform.startswith("win") and getattr(sys, "frozen", False)):
        return
    try:
        import ctypes

        ATTACH_PARENT_PROCESS = -1
        if ctypes.windll.kernel32.AttachConsole(ATTACH_PARENT_PROCESS):
            sys.stdout = open("CONOUT$", "w", encoding="utf-8", errors="replace")
            sys.stderr = open("CONOUT$", "w", encoding="utf-8", errors="replace")
    except Exception:
        pass


def main() -> int:
    # Any CLI flag (e.g. --input) routes to the headless CLI; otherwise GUI.
    argv = sys.argv[1:]
    if argv:
        _attach_parent_console()
        from pdfconv.logsetup import install_excepthook, setup_logging
        setup_logging()
        install_excepthook()
        from pdfconv.cli import run
        return run(argv)
    from pdfconv.logsetup import setup_logging
    setup_logging()
    from pdfconv.gui import main as gui_main
    gui_main()
    return 0


if __name__ == "__main__":
    multiprocessing.freeze_support()
    sys.exit(main())
