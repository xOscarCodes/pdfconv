"""Conversion engine — shared by the GUI and the CLI.

Design constraints that shape this module:

* **Picklable workers.** :func:`convert_one` and :func:`probe_pdf` are
  module-level functions taking plain dicts, so a ``ProcessPoolExecutor`` can
  ship them to worker processes under both ``fork`` (Linux) and ``spawn``
  (Windows / frozen builds). This module must therefore stay free of GUI
  imports — importing it must be cheap and side-effect free.
* **Integrity.** Every output is written to a temporary file in the destination
  directory and then atomically moved into place with :func:`os.replace`. A
  crash, exception, or cancellation can never leave a half-written ``.docx`` or
  ``.md`` behind.
* **Isolation.** Each file is converted in its own ``try/except``; one bad PDF
  never aborts a batch.
"""
from __future__ import annotations

import logging
import os
import shutil
import statistics
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

# pdf2docx and PyMuPDF are heavy; import lazily inside functions so that merely
# importing this module (which spawn does in every worker) stays cheap and so a
# missing optional dependency surfaces as a clear per-file error, not an import
# crash of the whole process.

# Quiet pdf2docx's chatty page-by-page logging in workers.
logging.getLogger("pdf2docx").setLevel(logging.ERROR)


# --- Status constants ------------------------------------------------------
QUEUED = "queued"
CONVERTING = "converting"
SCANNING = "scanning"      # running OCR
DONE = "done"
NOTEXT = "notext"          # scanned / no extractable text layer
FAILED = "failed"
ENCRYPTED = "encrypted"    # locked, needs a password

SUPPORTED_FORMATS = ("docx", "md")

# Decrypt/OCR intermediates go to a dedicated app temp dir (not the user's
# folders) so a startup sweep can reclaim any left behind by a hard-killed
# worker (where convert_one's finally never ran).
APP_TEMP = Path(tempfile.gettempdir()) / "pdfconv-tmp"
_TEMP_PREFIX = "pdfconv-"


def _make_temp(suffix: str, kind: str) -> str:
    """Create an app temp file and return its path (caller owns deletion)."""
    APP_TEMP.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(suffix=suffix, prefix=f"{_TEMP_PREFIX}{kind}-", dir=str(APP_TEMP))
    os.close(fd)
    return name


def temp_sweep(max_age_s: int = 3600) -> None:
    """Best-effort removal of stale app temp files (older than *max_age_s*)."""
    try:
        if not APP_TEMP.exists():
            return
        now = time.time()
        for p in APP_TEMP.glob(f"{_TEMP_PREFIX}*"):
            try:
                if now - p.stat().st_mtime > max_age_s:
                    p.unlink()
            except OSError:
                pass
    except Exception:
        pass


@dataclass
class PdfInfo:
    """Result of probing a PDF before conversion."""

    pages: int = 0
    has_text: bool = False
    encrypted: bool = False
    error: Optional[str] = None


# --------------------------------------------------------------------------
# Probing
# --------------------------------------------------------------------------
def probe_pdf(path: str) -> PdfInfo:
    """Inspect *path*: page count, whether a text layer exists, encryption.

    Never raises — a corrupt/unreadable file is reported via ``error``.
    """
    try:
        import fitz  # PyMuPDF
    except Exception as exc:  # pragma: no cover - dependency guard
        return PdfInfo(error=f"PyMuPDF (fitz) not available: {exc}")

    doc = None
    try:
        doc = fitz.open(path)
        if doc.needs_pass:
            # Page count is still readable for an encrypted doc in most cases.
            return PdfInfo(pages=doc.page_count, has_text=False, encrypted=True)
        pages = doc.page_count
        has_text = _has_text_layer(doc)
        return PdfInfo(pages=pages, has_text=has_text, encrypted=False)
    except Exception as exc:
        return PdfInfo(error=str(exc))
    finally:
        if doc is not None:
            try:
                doc.close()
            except Exception:
                pass


def _has_text_layer(doc) -> bool:
    """True if *any* page yields non-whitespace extractable text."""
    for page in doc:
        if page.get_text("text").strip():
            return True
    return False


# --------------------------------------------------------------------------
# Output path resolution (called in the parent process, single-threaded, to
# avoid races between workers writing to the same directory).
# --------------------------------------------------------------------------
def resolve_output_path(
    src: Path,
    fmt: str,
    output_mode: str,
    output_dir: Optional[Path],
    *,
    mirror_root: Optional[Path] = None,
    prefix: str = "",
    suffix: str = "",
    overwrite: bool = False,
) -> Path:
    """Compute the final destination path for *src*.

    * ``output_mode`` ``"next"`` -> alongside the source; ``"choose"`` -> under
      *output_dir*.
    * ``mirror_root`` (with ``output_dir``) recreates the source's relative
      subfolder tree under the output directory (FR-15).
    * ``prefix``/``suffix`` wrap the stem (FR-16).
    * When *overwrite* is False, a name clash is auto-renamed ``name (1).ext``.
    """
    ext = ".docx" if fmt == "docx" else ".md"
    stem = f"{prefix}{src.stem}{suffix}"

    if output_mode == "choose" and output_dir is not None:
        base_dir = Path(output_dir)
        if mirror_root is not None:
            try:
                rel = src.parent.relative_to(mirror_root)
                base_dir = base_dir / rel
            except ValueError:
                pass  # src not under mirror_root -> flat output
    else:
        base_dir = src.parent

    dst = base_dir / f"{stem}{ext}"
    if overwrite:
        return dst
    return _dedupe(dst)


def _dedupe(dst: Path) -> Path:
    """Return *dst* or the first free ``name (n).ext`` variant."""
    if not dst.exists():
        return dst
    stem, ext, parent = dst.stem, dst.suffix, dst.parent
    n = 1
    while True:
        candidate = parent / f"{stem} ({n}){ext}"
        if not candidate.exists():
            return candidate
        n += 1


# --------------------------------------------------------------------------
# The worker — runs in a child process.
# --------------------------------------------------------------------------
def convert_one(task: dict) -> dict:
    """Convert a single PDF. *task* and the return value are both picklable.

    Expected ``task`` keys: ``id``, ``src``, ``dst``, ``fmt``, ``start``,
    ``end``, ``overwrite``, ``ocr``, ``password``.

    Returns a dict: ``{"id", "status", "message", "duration", "dst"}`` where
    ``status`` is one of DONE / NOTEXT / FAILED / ENCRYPTED.
    """
    # pdf2docx reconfigures logging on import; silence its per-page chatter in
    # the worker process so neither the CLI nor a frozen build spews to stderr.
    logging.getLogger().setLevel(logging.ERROR)
    logging.getLogger("pdf2docx").setLevel(logging.ERROR)

    fid = task.get("id")
    src = Path(task["src"])
    dst = Path(task["dst"])
    fmt = task.get("fmt", "docx")
    start = task.get("start")
    end = task.get("end")
    ocr = bool(task.get("ocr"))
    password = task.get("password")
    t0 = time.perf_counter()

    def result(status: str, message: str = "") -> dict:
        return {
            "id": fid,
            "status": status,
            "message": message,
            "duration": time.perf_counter() - t0,
            "dst": str(dst),
        }

    tmp_decrypted: Optional[str] = None
    tmp_ocr: Optional[str] = None
    try:
        import fitz  # PyMuPDF
    except Exception as exc:  # pragma: no cover
        return result(FAILED, f"PyMuPDF (fitz) not available: {exc}")

    try:
        if not src.exists():
            return result(FAILED, "Source file no longer exists.")

        # --- Handle encryption ------------------------------------------
        doc = fitz.open(str(src))
        try:
            needs_pass = doc.needs_pass
        finally:
            doc.close()

        work_path = src
        if needs_pass:
            if not password:
                return result(ENCRYPTED, "Password required.")
            tmp_decrypted = _decrypt_to_temp(src, password)
            if tmp_decrypted is None:
                return result(FAILED, "Wrong password — could not unlock.")
            work_path = Path(tmp_decrypted)

        # --- Detect text layer / OCR ------------------------------------
        doc = fitz.open(str(work_path))
        try:
            has_text = _has_text_layer(doc)
            page_count = doc.page_count
        finally:
            doc.close()

        # Reject a page range that begins past the end of the document, so an
        # out-of-range selection FAILS clearly instead of writing an empty file.
        if start is not None and page_count and start >= page_count:
            return result(
                FAILED,
                f"Start page {start} is past the last page (document has "
                f"{page_count} page(s), 0-indexed).",
            )

        if not has_text:
            if ocr:
                tmp_ocr = _run_ocr(work_path)
                if tmp_ocr is None:
                    return result(
                        NOTEXT,
                        "Scanned PDF and OCR tooling (ocrmypdf) is not "
                        "installed — install it or convert a text-based PDF.",
                    )
                work_path = Path(tmp_ocr)
            else:
                return result(
                    NOTEXT,
                    "No text layer (scanned image). Enable OCR or convert a "
                    "text-based PDF.",
                )

        # --- Convert ----------------------------------------------------
        if fmt == "docx":
            _convert_docx(work_path, dst, start, end)
        elif fmt == "md":
            _convert_markdown(work_path, dst, start, end)
        else:
            return result(FAILED, f"Unsupported format: {fmt!r}")

        return result(DONE)

    except Exception as exc:  # noqa: BLE001 - isolate every failure
        return result(FAILED, f"{type(exc).__name__}: {exc}")
    finally:
        for tmp in (tmp_decrypted, tmp_ocr):
            if tmp:
                try:
                    os.unlink(tmp)
                except OSError:
                    pass


# --------------------------------------------------------------------------
# Conversion primitives
# --------------------------------------------------------------------------
def _atomic_write(dst: Path, write_fn) -> None:
    """Run ``write_fn(tmp_path)`` then atomically move the result onto *dst*.

    Guarantees *dst* is only ever the complete output — never a partial file.
    """
    dst.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(suffix=dst.suffix, prefix=".pdfconv-", dir=str(dst.parent))
    os.close(fd)
    tmp_path = Path(tmp_name)
    try:
        write_fn(tmp_path)
        os.replace(tmp_path, dst)  # atomic on the same filesystem; overwrites
    except BaseException:
        # Clean up the temp file on any failure (including cancellation).
        try:
            if tmp_path.exists():
                os.unlink(tmp_path)
        except OSError:
            pass
        raise


def _convert_docx(src: Path, dst: Path, start, end) -> None:
    """PDF -> DOCX via pdf2docx, written atomically."""
    from pdf2docx import Converter

    # pdf2docx calls logging.basicConfig(level=INFO) on import, re-enabling its
    # per-page chatter; lower the root level again now that it's imported.
    logging.getLogger().setLevel(logging.ERROR)

    # Our contract is an INCLUSIVE 0-indexed end (matching the Markdown writer
    # and the CLI help). pdf2docx's `end` is EXCLUSIVE, so add 1 — otherwise the
    # last requested page is silently dropped and start==end yields nothing.
    pd_end = None if end is None else end + 1

    def _write(tmp_path: Path) -> None:
        cv = Converter(str(src))
        try:
            cv.convert(str(tmp_path), start=start or 0, end=pd_end)
        finally:
            cv.close()

    _atomic_write(dst, _write)


def _convert_markdown(src: Path, dst: Path, start, end) -> None:
    """PDF -> Markdown via PyMuPDF text extraction, written atomically."""
    import fitz

    def _write(tmp_path: Path) -> None:
        doc = fitz.open(str(src))
        try:
            first = start or 0
            last = doc.page_count if end is None else min(end + 1, doc.page_count)
            md_parts: list[str] = []
            for pno in range(first, last):
                md_parts.append(_page_to_markdown(doc[pno]))
            text = "\n\n".join(p for p in md_parts if p).strip() + "\n"
        finally:
            doc.close()
        tmp_path.write_text(text, encoding="utf-8")

    _atomic_write(dst, _write)


def _page_to_markdown(page) -> str:
    """Convert one PyMuPDF page to Markdown.

    Heuristics: a font size meaningfully larger than the page's body size
    becomes a heading (``#``/``##``/``###``); other blocks become paragraphs.
    Tables, when PyMuPDF can detect them, render as GitHub-style tables.
    """
    blocks = page.get_text("dict").get("blocks", [])
    # Gather span sizes to establish the body text size.
    sizes: list[float] = []
    for b in blocks:
        for line in b.get("lines", []):
            for span in line.get("spans", []):
                if span.get("text", "").strip():
                    sizes.append(round(span["size"], 1))
    body_size = statistics.median(sizes) if sizes else 0.0

    # Detect tables and the rectangles they occupy (best-effort).
    table_md: list[str] = []
    table_rects = []
    try:
        finder = page.find_tables()
        for tbl in finder.tables:
            table_md.append(_table_to_markdown(tbl.extract()))
            table_rects.append(fitz_rect(tbl.bbox))
    except Exception:
        pass

    out: list[str] = []
    for b in blocks:
        if b.get("type", 0) != 0:  # skip image blocks
            continue
        bbox = b.get("bbox")
        if bbox and _inside_any(bbox, table_rects):
            continue  # text belongs to a detected table; rendered separately
        block_text_parts: list[str] = []
        max_size = 0.0
        for line in b.get("lines", []):
            line_text = "".join(span.get("text", "") for span in line.get("spans", [])).strip()
            if line_text:
                block_text_parts.append(line_text)
            for span in line.get("spans", []):
                if span.get("text", "").strip():
                    max_size = max(max_size, round(span["size"], 1))
        block_text = " ".join(block_text_parts).strip()
        if not block_text:
            continue
        out.append(_format_block(block_text, max_size, body_size))

    # Append any detected tables after the flowing text of the page.
    out.extend(table_md)
    return "\n\n".join(out)


def _format_block(text: str, size: float, body: float) -> str:
    """Tag *text* as a heading or paragraph based on its font *size*."""
    if body and size >= body * 1.5:
        return f"# {text}"
    if body and size >= body * 1.25:
        return f"## {text}"
    if body and size >= body * 1.1:
        return f"### {text}"
    return text


def _table_to_markdown(rows) -> str:
    """Render a list-of-rows table as a GitHub-flavoured Markdown table."""
    cleaned = [[("" if c is None else str(c)).replace("\n", " ").strip() for c in row] for row in rows]
    cleaned = [r for r in cleaned if any(cell for cell in r)]
    if not cleaned:
        return ""
    width = max(len(r) for r in cleaned)
    cleaned = [r + [""] * (width - len(r)) for r in cleaned]
    header = cleaned[0]
    lines = ["| " + " | ".join(header) + " |", "| " + " | ".join(["---"] * width) + " |"]
    for r in cleaned[1:]:
        lines.append("| " + " | ".join(r) + " |")
    return "\n".join(lines)


def fitz_rect(bbox):
    """Wrap a bbox tuple so :func:`_inside_any` can compare overlaps."""
    return tuple(bbox)


def _inside_any(bbox, rects, min_frac: float = 0.7) -> bool:
    """True if *bbox* is substantially (>= *min_frac* of its area) inside a rect.

    Area overlap rather than a centroid test, so a heading or caption that merely
    grazes an over-extended table bounding box isn't silently dropped.
    """
    if not rects:
        return False
    bx0, by0, bx1, by1 = bbox
    barea = max(1e-6, (bx1 - bx0) * (by1 - by0))
    for r in rects:
        ix0, iy0 = max(bx0, r[0]), max(by0, r[1])
        ix1, iy1 = min(bx1, r[2]), min(by1, r[3])
        if ix1 > ix0 and iy1 > iy0:
            if (ix1 - ix0) * (iy1 - iy0) / barea >= min_frac:
                return True
    return False


# --------------------------------------------------------------------------
# Encryption / OCR helpers
# --------------------------------------------------------------------------
def _decrypt_to_temp(src: Path, password: str) -> Optional[str]:
    """Decrypt *src* with *password* into a temp PDF. None on wrong password."""
    try:
        import pikepdf
    except Exception:
        # Fall back to PyMuPDF if pikepdf is unavailable.
        return _decrypt_to_temp_fitz(src, password)

    try:
        with pikepdf.open(str(src), password=password) as pdf:
            tmp_name = _make_temp(".pdf", "dec")
            pdf.save(tmp_name)
            return tmp_name
    except pikepdf.PasswordError:
        return None
    except Exception:
        return _decrypt_to_temp_fitz(src, password)


def _decrypt_to_temp_fitz(src: Path, password: str) -> Optional[str]:
    """PyMuPDF fallback decryptor."""
    import fitz

    doc = None
    try:
        doc = fitz.open(str(src))
        if doc.authenticate(password) == 0:
            return None
        tmp_name = _make_temp(".pdf", "dec")
        doc.save(tmp_name)
        return tmp_name
    except Exception:
        return None
    finally:
        if doc is not None:
            try:
                doc.close()
            except Exception:
                pass


def _run_ocr(src: Path) -> Optional[str]:
    """Run OCR on *src* into a temp searchable PDF. None if tooling absent.

    Uses the ``ocrmypdf`` CLI when present (which wraps Tesseract). This is the
    optional FR-12 path; the app ships with OCR off by default.
    """
    if shutil.which("ocrmypdf") is None:
        return None
    tmp_name = _make_temp(".pdf", "ocr")
    try:
        import subprocess

        proc = subprocess.run(
            ["ocrmypdf", "--force-ocr", "--quiet", str(src), tmp_name],
            capture_output=True,
            text=True,
        )
        if proc.returncode != 0:
            os.unlink(tmp_name)
            return None
        return tmp_name
    except Exception:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        return None


# --------------------------------------------------------------------------
# File discovery (shared by GUI "Add folder" and CLI)
# --------------------------------------------------------------------------
def discover_pdfs(path: Path, recursive: bool = True) -> list[Path]:
    """Return sorted ``.pdf`` files under *path* (or just *path* if it's a file)."""
    path = Path(path)
    if path.is_file():
        return [path] if path.suffix.lower() == ".pdf" else []
    pattern = "**/*.pdf" if recursive else "*.pdf"
    return sorted(p for p in path.glob(pattern) if p.is_file())
