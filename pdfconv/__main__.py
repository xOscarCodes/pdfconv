"""``python -m pdfconv`` — same behaviour as the ``pdf2docx_app.py`` entry point.

No arguments launches the GUI; any argument routes to the headless CLI. The
``freeze_support()`` call and the ``__main__`` guard keep the ``spawn``-based
process pool working on Windows/macOS and in frozen builds.
"""
from __future__ import annotations

import multiprocessing
import sys


def _main() -> int:
    argv = sys.argv[1:]
    if argv:
        from .logsetup import install_excepthook, setup_logging

        setup_logging()
        install_excepthook()
        from .cli import run

        return run(argv)
    from .logsetup import setup_logging

    setup_logging()
    from .gui import main as gui_main

    gui_main()
    return 0


if __name__ == "__main__":
    multiprocessing.freeze_support()
    sys.exit(_main())
