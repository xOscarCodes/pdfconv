# Production & Cross-Platform Hardening — Design

**Date:** 2026-06-23
**Status:** Approved (proceeding to implementation)

## Goal

Ship the existing PDF → DOCX / Markdown converter as production-quality software
that runs correctly on **Windows, Linux, and macOS**. The primary deliverable is
"just a Python file you run," documented so well that anyone on any OS can install
and run it locally. Optional portable binaries remain a secondary path.

## Scope (decided with the product owner)

- **In:** genuine macOS correctness; polish (app icon, rotating logs, global crash
  handler + friendly dialog, About/version); first-class run-from-source UX and
  per-OS documentation; `pyproject.toml` with console entry points; a small engine
  smoke test; a tri-platform PyInstaller build (incl. a macOS `.app`).
- **Out:** CI matrix; native OS installers (MSI/DMG/deb); code signing /
  notarization (not needed for run-from-source — saves the Apple/Windows cert cost);
  auto-update; full test suite.

## Decisions

1. **Run-from-source is primary.** Three supported invocations, all identical in
   behaviour: `python pdf2docx_app.py`, `python -m pdfconv`, and (after install)
   the `pdf2docx` / `pdf2docx-gui` console scripts.
2. **Assets live inside the package** (`pdfconv/assets/`) so they ship with a source
   checkout, a `pip install`, and a frozen build (`sys._MEIPASS` aware).
3. **multiprocessing uses an explicit `spawn` context everywhere.** macOS (3.8+) and
   Windows already default to spawn; forcing spawn on Linux too removes the
   fork-from-a-multithreaded-GUI deadlock risk and makes all three OSes behave
   identically. Workers are already module-level + picklable, so this is safe.
4. **Logging is centralized** in `pdfconv/logsetup.py`: a rotating file at
   `~/.pdfconverter/logs/app.log` plus a global `sys.excepthook` /
   `threading.excepthook` and a Tk `report_callback_exception` that log full
   tracebacks and show a friendly error dialog in the GUI.

## Components & file-by-file changes

| File | Change |
|---|---|
| `pdfconv/logsetup.py` *(new)* | Rotating-file logging + excepthook installers. Idempotent. |
| `pdfconv/__main__.py` *(new)* | `python -m pdfconv` entry, spawn-safe (`freeze_support` + guard). |
| `pdfconv/platform_utils.py` | macOS `notify()` branch via `osascript`; `asset_path()` helper (frozen-aware); debug-logging instead of silent `pass`. |
| `pdfconv/theme.py` | Font stacks gain macOS (`Helvetica Neue`, `Menlo`, `Monaco`) and explicit SF families; Windows order unchanged. |
| `pdfconv/gui.py` | Window icon; About dialog (brand mark, version, platform, open-log); Tk crash hook + crash dialog; `spawn` mp context; notify caption mentions macOS; key run events logged to file. |
| `pdfconv/cli.py` | `--version`; `spawn` mp context; `main_cli()` entry wrapper that sets up logging. |
| `pdf2docx_app.py` | Set up logging + excepthook for both GUI and CLI paths. |
| `pdfconv/assets/` *(new)* | `icon.png` (1024), `icon.ico`, `icon.icns`, generated from the brand mark. |
| `tools/make_icons.py` *(new)* | Deterministic icon generator (gradient rounded tile + white file-check glyph). |
| `pyproject.toml` *(new)* | PEP 621 metadata, pinned deps, `[dnd]`/`[ocr]`/`[dev]` extras, console scripts, package-data for assets. |
| `run.sh` / `run.bat` *(new)* | One-step launchers (create venv, install deps, run). |
| `pdf2docx_app.spec` | Tri-platform: per-OS icon, bundle `pdfconv/assets`, macOS `.app` `BUNDLE` with `Info.plist`. |
| `tests/test_engine.py` *(new)* | Smoke tests: docx + md output, encrypted, corrupt, out-of-range pages. |
| `README.md` | Rewritten: Windows/macOS/Linux quickstart, Tkinter + Tesseract prereqs, run scripts, install, troubleshooting, build. |

## `logsetup` public API (consumed by gui/cli/entry)

```python
setup_logging(level=logging.INFO) -> Path        # idempotent; returns LOG_PATH
install_excepthook(on_crash=None) -> None         # sys + threading excepthook
LOG_DIR: Path                                     # ~/.pdfconverter/logs
LOG_PATH: Path                                    # ~/.pdfconverter/logs/app.log
```

## Testing / verification

- `python -m py_compile` over every module (syntax).
- `import pdfconv` and `python pdf2docx_app.py --version` (smoke).
- `pytest tests/` round-trips a generated PDF → docx/md and exercises the
  encrypted / corrupt / out-of-range paths.
- Adversarial multi-lens review of the diff (cross-platform correctness, regressions,
  docs accuracy).

## Honesty notes

- Development happens on Windows; macOS/Linux code is written for correctness and
  documented, but final verification on those OSes is the owner running the
  documented steps (CI was declined).
- `pdf2docx_app.py`'s existing `ctypes.windll` use is already correctly guarded;
  no change needed there (audit flagged it, but the guard holds).
