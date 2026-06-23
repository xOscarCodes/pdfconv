"""Headless CLI (FR-24) — shares the conversion engine with the GUI.

Example::

    python pdf2docx_app.py --input report.pdf --output out/
    python pdf2docx_app.py --input ./pdfs --output out/ --recursive --jobs 4 --format md

Prints per-file progress and an end-of-run summary; exits non-zero if any file
failed (scanned / encrypted files count as skipped, not failures).
"""
from __future__ import annotations

import argparse
import multiprocessing
import sys
import os
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

from . import __version__, engine


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="pdf2docx_app",
        description="Convert PDFs to editable Word (.docx) or Markdown (.md).",
    )
    p.add_argument("--version", action="version",
                   version=f"%(prog)s {__version__}")
    p.add_argument("--input", required=True, help="A PDF file or a folder of PDFs.")
    p.add_argument("--output", help="Output folder (default: alongside each source).")
    p.add_argument("--format", choices=engine.SUPPORTED_FORMATS, default="docx",
                   help="Output format (default: docx).")
    p.add_argument("--start", type=int, default=None, help="First page (0-indexed).")
    p.add_argument("--end", type=int, default=None, help="Last page (0-indexed, inclusive).")
    p.add_argument("--overwrite", action="store_true", help="Overwrite existing outputs.")
    p.add_argument("--jobs", type=int, default=None,
                   help="Parallel workers (default: CPU - 1).")
    p.add_argument("--recursive", action="store_true",
                   help="Recurse into subfolders when --input is a folder.")
    p.add_argument("--ocr", action="store_true",
                   help="OCR scanned PDFs (requires ocrmypdf on PATH).")
    p.add_argument("--password", default=None,
                   help="Password for encrypted PDFs (applied to all inputs).")
    p.add_argument("--mirror", action="store_true",
                   help="Mirror source subfolders under --output.")
    p.add_argument("--prefix", default="", help="Prefix added to each output filename.")
    p.add_argument("--suffix", default="", help="Suffix added to each output filename (before the extension).")
    return p


def _validate_pages(start, end) -> None:
    if start is not None and start < 0:
        raise SystemExit("error: --start must be >= 0")
    if end is not None and end < 0:
        raise SystemExit("error: --end must be >= 0")
    if start is not None and end is not None and start > end:
        raise SystemExit("error: --start must be <= --end")


def run(argv: list[str]) -> int:
    args = build_parser().parse_args(argv)
    _validate_pages(args.start, args.end)
    engine.temp_sweep()  # reclaim any temp files orphaned by a prior hard kill

    in_path = Path(args.input).expanduser()
    if not in_path.exists():
        print(f"error: input not found: {in_path}", file=sys.stderr)
        return 2

    pdfs = engine.discover_pdfs(in_path, recursive=args.recursive)
    if not pdfs:
        print(f"error: no .pdf files found in {in_path}", file=sys.stderr)
        return 2

    out_dir = Path(args.output).expanduser() if args.output else None
    output_mode = "choose" if out_dir else "next"
    mirror_root = in_path if (args.mirror and in_path.is_dir() and out_dir) else None
    default_jobs = max(1, (os.cpu_count() or 2) - 1)
    workers = args.jobs if (args.jobs and args.jobs > 0) else default_jobs
    workers = max(1, min(workers, len(pdfs)))

    tasks = []
    for i, src in enumerate(pdfs):
        dst = engine.resolve_output_path(
            src, args.format, output_mode, out_dir,
            mirror_root=mirror_root, prefix=args.prefix, suffix=args.suffix,
            overwrite=args.overwrite,
        )
        tasks.append({
            "id": i, "src": str(src), "dst": str(dst), "fmt": args.format,
            "start": args.start, "end": args.end, "overwrite": args.overwrite,
            "ocr": args.ocr, "password": args.password,
        })

    total = len(tasks)
    print(f"Converting {total} file(s) to {args.format.upper()} with {workers} worker(s)…")
    ok = fail = skip = 0
    done = 0

    # Force the 'spawn' start method everywhere: it is the default on Windows and
    # macOS, and using it on Linux too keeps worker behaviour identical across
    # platforms (the engine's workers are module-level and picklable).
    mp_ctx = multiprocessing.get_context("spawn")
    with ProcessPoolExecutor(max_workers=workers, mp_context=mp_ctx) as ex:
        future_to_task = {ex.submit(engine.convert_one, t): t for t in tasks}
        for fut in as_completed(future_to_task):
            t = future_to_task[fut]
            try:
                res = fut.result()
            except Exception as exc:  # pragma: no cover - defensive
                res = {"status": engine.FAILED, "message": str(exc)}
            done += 1
            status = res["status"]
            name = Path(t["src"]).name
            if status == engine.DONE:
                ok += 1
                tag, detail = "OK   ", Path(res.get("dst", "")).name
            elif status in (engine.NOTEXT, engine.ENCRYPTED):
                skip += 1
                tag, detail = "SKIP ", res.get("message", "")
            else:
                fail += 1
                tag, detail = "FAIL ", res.get("message", "")
            print(f"[{done}/{total}] {tag} {name}  {detail}")

    print(f"\nDone: {ok} succeeded · {fail} failed · {skip} skipped")
    return 1 if fail else 0


def main_cli() -> int:
    """Console-script entry point (``pdf2docx``). Sets up logging, then runs.

    ``freeze_support`` keeps the spawn-based pool working under console scripts
    and frozen builds.
    """
    multiprocessing.freeze_support()
    from .logsetup import install_excepthook, setup_logging

    setup_logging()
    install_excepthook()
    return run(sys.argv[1:])
