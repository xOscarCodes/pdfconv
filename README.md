# PDF → DOCX · Markdown Converter

A **cross-platform** (Windows · macOS · Linux) desktop utility that converts PDFs
to editable **Word (`.docx`)** and **Markdown (`.md`)** files. It supports
single-file and batch (multi-file / whole-folder) conversion, runs conversions in
parallel across CPU cores, and ships an optional headless **CLI** that shares the
same engine.

The interface is a polished single-window app built with **customtkinter**: a file
queue with a live, colour-coded status system (the signature element), an options
strip, and a footer with progress, an end-of-run summary, and a collapsible log.

---

## Contents

- [Features](#features)
- [Quick start (easiest)](#quick-start-easiest)
- [Manual install](#manual-install)
- [Running the app](#running-the-app)
- [Optional extras (drag-and-drop, OCR)](#optional-extras)
- [Where your data lives](#where-your-data-lives)
- [Build a standalone executable](#build-a-standalone-executable)
- [Project layout](#project-layout)
- [Troubleshooting](#troubleshooting)
- [Running the tests](#running-the-tests)

---

## Features

| Area | Capabilities |
|---|---|
| Input | Add files (multi-select, `.pdf` only), add a whole folder (recursive), drag-and-drop¹ |
| Queue | Per-file name · page count · format · live colour-coded status; select / remove / clear |
| Engine | `pdf2docx` for DOCX, PyMuPDF text extraction for Markdown; parallel process pool |
| Robustness | Scanned/no-text PDFs flagged (never a silent empty file); encrypted PDFs reported + **Unlock**; corrupt files isolated — one bad PDF never aborts the batch |
| Output | "Next to source" or a chosen folder; auto-rename on clash or overwrite; mirror source subfolders; filename prefix/suffix |
| Control | Convert / Cancel (cancel leaves **zero partial files**); per-file + overall progress; Retry failed; Open output folder |
| Feedback | End-of-run summary; timestamped, colour-coded log; persistent audit log (CSV); rotating diagnostic log + crash dialog |
| QoL | Dark / light theme; parallel-worker cap; desktop notification on batch completion (Windows/macOS/Linux); settings persistence; About box |
| Automation | Headless CLI sharing the engine; `--version` |

¹ Drag-and-drop requires the optional `tkinterdnd2` package; the app degrades
gracefully without it.

---

## Quick start (easiest)

You need **Python 3.10 or newer**. The bundled launcher scripts create a private
virtual environment, install everything, and start the app — no manual steps.

### Windows

Double-click **`run.bat`**, or from a terminal:

```powershell
.\run.bat
```

### macOS / Linux

```bash
chmod +x run.sh      # first time only
./run.sh
```

> On Linux (and Homebrew Python on macOS) you may first need the Tk GUI library —
> see [Troubleshooting → Tkinter](#tkinter-no-module-named-tkinter). The launcher
> will tell you if it's missing.

Arguments are passed straight through, so the launchers can also run the CLI:

```bash
./run.sh --input report.pdf --output out/        # macOS / Linux
.\run.bat --input report.pdf --output out\       # Windows
```

---

## Manual install

Prefer to manage the environment yourself? Create a virtual environment and
install the dependencies.

```bash
# 1) create + activate a virtual environment
python -m venv .venv
#    Windows (PowerShell):  .venv\Scripts\Activate.ps1
#    Windows (cmd):         .venv\Scripts\activate.bat
#    macOS / Linux:         source .venv/bin/activate

# 2) install dependencies
pip install -r requirements.txt
```

### Or install it as a command (any OS)

Installing the project gives you two console commands anywhere on your PATH —
great with [`pipx`](https://pipx.pypa.io):

```bash
pipx install .         # or:  pip install .
pdf2docx-gui           # launch the GUI
pdf2docx --input report.pdf --output out/   # the CLI
```

### Platform prerequisites at a glance

| OS | Python | Tkinter (GUI toolkit) |
|---|---|---|
| **Windows** | [python.org](https://www.python.org/downloads/) installer | included |
| **macOS** | [python.org](https://www.python.org/downloads/) installer (recommended) | included. Homebrew Python: `brew install python-tk` |
| **Linux** | distro Python 3.10+ | Debian/Ubuntu: `sudo apt install python3-tk` · Fedora: `sudo dnf install python3-tkinter` · Arch: `sudo pacman -S tk` |

---

## Running the app

### GUI

```bash
python pdf2docx_app.py
# equivalently:  python -m pdfconv
```

Add files or a folder, pick **DOCX** or **Markdown**, set any options, and press
**Convert**. Encrypted files show an **Unlock** button; scanned (no-text) files are
flagged "No text" unless **OCR scanned PDFs** is enabled.

### CLI

The CLI activates whenever any flag is passed:

```bash
# single file, output beside the source
python pdf2docx_app.py --input report.pdf

# whole folder -> Markdown, into out/, 4 workers, recursive, mirroring subfolders
python pdf2docx_app.py --input ./pdfs --output out/ --format md --jobs 4 --recursive --mirror

# a page range (0-indexed, inclusive) and overwrite
python pdf2docx_app.py --input big.pdf --output out/ --start 0 --end 9 --overwrite

# an encrypted PDF
python pdf2docx_app.py --input locked.pdf --output out/ --password "s3cret"
```

| Flag | Meaning |
|---|---|
| `--input` | A `.pdf` file or a folder of PDFs (required) |
| `--output` | Output folder (default: alongside each source) |
| `--format` | `docx` (default) or `md` |
| `--start` / `--end` | Page range, 0-indexed, end inclusive (blank = whole document) |
| `--overwrite` | Overwrite existing outputs instead of auto-renaming |
| `--jobs` | Parallel workers (default: CPU − 1) |
| `--recursive` | Recurse into subfolders when `--input` is a folder |
| `--mirror` | Recreate source subfolders under `--output` |
| `--prefix` | Prefix added to each output filename |
| `--suffix` | Suffix added to each output filename (before the extension) |
| `--ocr` | OCR scanned PDFs (needs `ocrmypdf` on PATH) |
| `--password` | Password applied to encrypted inputs |
| `--version` | Print the version and exit |

The CLI prints per-file progress and a summary, and **exits non-zero if any file
failed** (scanned / encrypted files count as skipped, not failures).

---

## Optional extras

Both are off by default and the app works fully without them.

### Drag-and-drop

```bash
pip install tkinterdnd2        # or:  pip install ".[dnd]"
```

### OCR for scanned PDFs

OCR needs the `ocrmypdf` tool, which in turn needs **Tesseract** installed:

| OS | Install |
|---|---|
| **Windows** | Install [Tesseract (UB-Mannheim build)](https://github.com/UB-Mannheim/tesseract/wiki) and add it to PATH, then `pip install ocrmypdf` |
| **macOS** | `brew install tesseract ocrmypdf` |
| **Linux** | `sudo apt install tesseract-ocr ocrmypdf` (or your distro's equivalent) |

Then enable **OCR scanned PDFs** in the GUI, or pass `--ocr` on the CLI.

---

## Where your data lives

All under a single per-user folder (`~` = your home directory on every OS):

| Path | What |
|---|---|
| `~/.pdfconverter/config.json` | Saved settings (only when "Remember…" is on) |
| `~/.pdfconverter/audit.csv` | One row per converted file: time, source, destination, status, duration |
| `~/.pdfconverter/logs/app.log` | Rotating diagnostic log (also where crash details go) |

The **About** dialog (Settings → About) shows the version, your OS/Python, and a
button to open the log folder.

---

## Build a standalone executable

PyInstaller cannot cross-compile — **build on each target OS**. (A CI matrix of
`windows-latest` + `macos-latest` + `ubuntu-latest` is the clean way to produce
all three; not set up here by default.)

```bash
pip install pyinstaller        # or:  pip install ".[dev]"
python tools/make_icons.py     # (re)generate icon assets if needed
pyinstaller pdf2docx_app.spec
```

| OS | Artifact |
|---|---|
| Windows | `dist/pdf2docx_app.exe` |
| Linux | `dist/pdf2docx_app` |
| macOS | `dist/PDF Converter.app` (a real bundle with an Info.plist and icon) |

The spec bundles `pdf2docx`, PyMuPDF (`fitz`), `customtkinter`, and `pikepdf`
data/binaries, includes the `pdfconv/assets` icons, and adds the `pdfconv` package
to hidden imports so the `spawn`-based process pool works in the frozen build.

**Running an unsigned build on another machine.** These artifacts are not code-signed
(signing/notarization is only needed to distribute to *other* people's machines and
costs money — it isn't required to run the app yourself):

- **macOS** blocks unsigned apps via Gatekeeper. Either right-click the `.app` →
  **Open** → **Open**, or clear the quarantine flag:
  `xattr -dr com.apple.quarantine "dist/PDF Converter.app"`.
- **Windows** SmartScreen may warn on first run: click **More info → Run anyway**.

---

## Project layout

```
pdf2docx_app.py        # GUI + CLI entry point (the deliverable)
pdf2docx_app.spec      # PyInstaller build spec (Windows / macOS / Linux)
pyproject.toml         # packaging metadata + console scripts + extras
requirements.txt       # runtime dependencies
run.sh / run.bat       # one-step launchers (create venv, install, run)
tools/make_icons.py    # generates the app icon assets
tests/test_engine.py   # engine smoke tests (pytest)
pdfconv/
  engine.py            # conversion engine: probe, convert (docx/md), picklable workers
  gui.py               # customtkinter App surface (+ About + crash dialog)
  cli.py               # argparse headless CLI
  config.py            # JSON settings (~/.pdfconverter/config.json)
  audit.py             # CSV audit log (~/.pdfconverter/audit.csv)
  logsetup.py          # rotating logging + global crash handlers
  platform_utils.py    # open-folder / notifications / asset paths (Win/macOS/Linux)
  theme.py             # design tokens (slate & indigo), cross-platform fonts
  icons.py             # Lucide-style outline icons (canvas + PIL/CTkImage)
  __main__.py          # `python -m pdfconv`
  assets/              # icon.png / icon.ico / icon.icns
```

---

## Troubleshooting

### Tkinter: "No module named `tkinter`"

The GUI toolkit isn't bundled with every Python build. Install it:

- **Linux (Debian/Ubuntu):** `sudo apt install python3-tk`
- **Linux (Fedora):** `sudo dnf install python3-tkinter`
- **Linux (Arch):** `sudo pacman -S tk`
- **macOS (Homebrew Python):** `brew install python-tk`, or use the python.org
  installer which already includes Tk.

### The UI font looks generic

The app picks the best available native font (Segoe UI on Windows, SF Pro /
Helvetica Neue on macOS, Inter / Ubuntu / DejaVu on Linux) and falls back safely
if none are installed — functionality is unaffected.

### Desktop notifications don't appear

They're best-effort and OS-controlled: Windows uses a PowerShell toast, macOS uses
`osascript` (check System Settings → Notifications), Linux uses `notify-send`
(install `libnotify-bin` if absent). The conversion itself is unaffected.

### Something crashed

A full traceback is written to `~/.pdfconverter/logs/app.log`, and the GUI shows a
dialog pointing you there. Include that log when reporting an issue.

### Reduced motion

Set the environment variable `PDFCONV_REDUCED_MOTION=1` to disable all animations.

---

## Running the tests

```bash
pip install pytest        # or:  pip install ".[dev]"
pytest
```

The suite generates tiny PDFs on the fly and checks DOCX + Markdown output plus the
encrypted, corrupt, and out-of-range-page paths. No fixtures or network needed.
