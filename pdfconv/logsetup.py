"""Centralised logging and crash handling.

Everything writes to a rotating file at ``~/.pdfconverter/logs/app.log`` so that
when something goes wrong there is always a diagnosable record, regardless of
whether the app was launched from a terminal, a desktop shortcut, or a frozen
build with no console.

Two installers are exposed:

* :func:`setup_logging` — wire up the rotating file handler (idempotent).
* :func:`install_excepthook` — route otherwise-unhandled exceptions (main thread
  *and* background threads) to the log, with an optional GUI callback.

This module is import-cheap and free of GUI/heavy imports so the entry point can
configure logging before anything else loads.
"""
from __future__ import annotations

import logging
import logging.handlers
import sys
import threading
from pathlib import Path

from .config import APP_DIR

LOG_DIR = APP_DIR / "logs"
LOG_PATH = LOG_DIR / "app.log"

_FORMAT = "%(asctime)s %(levelname)-8s %(name)s: %(message)s"
_configured = False


class _SafeRotatingFileHandler(logging.handlers.RotatingFileHandler):
    """A rotating handler whose rollover can never crash logging.

    On Windows, rotating the log fails if a second instance of the app holds the
    file open (``os.replace`` raises ``PermissionError``). Swallow that and keep
    writing to the current file rather than letting logging error out.
    """

    def doRollover(self):  # noqa: D102
        try:
            super().doRollover()
        except Exception:
            pass


def setup_logging(level: int = logging.INFO) -> Path:
    """Attach a rotating file handler (and a console handler) to the root logger.

    Idempotent: safe to call from every entry point. Returns the log file path.

    pdf2docx calls ``logging.basicConfig`` on import; by attaching our own
    handlers first we make that call a no-op in this (the parent) process, so the
    GUI/CLI never inherit its INFO-level page-by-page chatter.
    """
    global _configured
    if _configured:
        return LOG_PATH
    try:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        root = logging.getLogger()
        root.setLevel(level)
        fmt = logging.Formatter(_FORMAT)

        fh = _SafeRotatingFileHandler(
            LOG_PATH, maxBytes=1_000_000, backupCount=3, encoding="utf-8", delay=True
        )
        fh.setLevel(level)
        fh.setFormatter(fmt)
        root.addHandler(fh)

        # A console handler for warnings and above, so terminal users still see
        # problems. Guarded: a frozen windowed build may have no stderr.
        if sys.stderr is not None:
            ch = logging.StreamHandler()
            ch.setLevel(logging.WARNING)
            ch.setFormatter(fmt)
            root.addHandler(ch)

        # Keep pdf2docx quiet in this process regardless of import order.
        logging.getLogger("pdf2docx").setLevel(logging.ERROR)
        _configured = True
        logging.getLogger("pdfconv").debug("Logging initialised -> %s", LOG_PATH)
    except Exception:
        # Logging must never be the thing that crashes the app.
        pass
    return LOG_PATH


def install_excepthook(on_crash=None) -> None:
    """Send uncaught exceptions to the log; optionally invoke *on_crash(exc)*.

    Installs hooks for both the main thread (:data:`sys.excepthook`) and worker
    threads (:data:`threading.excepthook`, Python 3.8+). ``KeyboardInterrupt`` is
    passed through to the default handler so Ctrl-C still works.
    """
    log = logging.getLogger("pdfconv")

    def _handle(exc_type, exc_value, exc_tb):
        if issubclass(exc_type, KeyboardInterrupt):
            sys.__excepthook__(exc_type, exc_value, exc_tb)
            return
        log.critical("Uncaught exception", exc_info=(exc_type, exc_value, exc_tb))
        if on_crash is not None:
            try:
                on_crash(exc_value)
            except Exception:
                pass

    sys.excepthook = _handle

    def _thread_handle(args):
        if issubclass(args.exc_type, KeyboardInterrupt):
            return
        log.critical(
            "Uncaught exception in thread %s",
            getattr(args.thread, "name", "?"),
            exc_info=(args.exc_type, args.exc_value, args.exc_traceback),
        )
        if on_crash is not None:
            try:
                on_crash(args.exc_value)
            except Exception:
                pass

    try:
        threading.excepthook = _thread_handle
    except Exception:
        pass
