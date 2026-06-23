# MarkItAll v2.0 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn the PDF→DOCX/MD tool into a universal "any supported document → Markdown (plus PDF → Word)" converter powered by Microsoft `markitdown`, and expose it to AI agents via an MCP server.

**Architecture:** One shared, picklable, GUI-free engine (`pdfconv/engine.py`) routes Markdown output through `markitdown` for every input type and DOCX output through `pdf2docx` for PDF only. A new empty-output guard (`NoTextError`) preserves the "never a silent empty file" invariant. CLI, GUI, and a new stdio MCP server (`pdfconv/mcp_server.py`) are thin frontends over the engine. Tasks are dependency-ordered: deps → engine → CLI/GUI → MCP → tests/docs.

**Tech Stack:** Python ≥3.10, `markitdown[all]`, `pdf2docx`/PyMuPDF, `pikepdf`, `customtkinter`, MCP Python SDK (`mcp`, FastMCP), optional `openai` (image captions), `pytest`.

**Authoritative spec:** `docs/superpowers/specs/2026-06-23-markitdown-universal-converter-mcp-design.md` (read it; this plan operationalizes it).

## Global Constraints

- Python floor **>=3.10** (markitdown, mcp, current project all agree).
- License stays **AGPL-3.0**; no new copyleft. Decisions are FIXED: markitdown[all] in core; **audio/video & URL/YouTube inputs are out of scope** (not in `SUPPORTED_EXTENSIONS`); `.doc`/`.ppt` **excluded** (no markitdown converter), `.xls` **included**.
- Dependency pins: `markitdown[all]>=0.1,<0.2` (core), `mcp>=1.10,<2` (`[mcp]` extra — the `<2` bound preserves `from mcp.server.fastmcp import FastMCP`), `openai` (`[llm]` extra).
- Engine stays **GUI-free and import-cheap**; heavy imports (`fitz`, `markitdown`, `openai`) are **lazy inside functions** (spawn-safe). Workers are module-level + picklable; pool uses the existing `spawn` context.
- Output integrity: **never `os.replace` a 0-content `.md`**; empty/whitespace conversion → `NOTEXT`, no file written.
- Entry-point identifiers DO NOT change: `[project].name` stays `pdfconv`; console scripts `pdf2docx`/`pdf2docx-gui`, `pdf2docx_app.py`, and CLI `prog="pdf2docx_app"` unchanged. Only `version` → `2.0.0`, description/keywords broaden, UI copy rebrands to "MarkItAll".
- Run commands on Windows via `./.venv/Scripts/python.exe`. Conversions need native paths (PyMuPDF rejects Git-Bash `/c/...` paths in tests — use `tmp_path`).
- **UI consistency (REQUIRED):** every new or changed GUI element must use the existing slate-and-indigo design system — `theme.py` tokens (colors, `R_*` radii, the `ST_*` status palette, `ACCENT*`, `BORDER*`, `SURFACE`/`BG`), `self.fonts.*` (never raw font-family/size literals), the `_icon(...)` helper for glyphs, and the settings-drawer builders (`_section` / `_caption` / `_rule` / `_switch`). No ad-hoc hex colors, font names, magic sizes, or one-off widget styling. New status colors come only from the existing `ST_*` palette, and the skip-family statuses (`NOTEXT` / `ENCRYPTED` / `SKIPPED`) must read as a coherent group. New dialogs/sections match the padding, corner radius, and button styling of existing ones (e.g. mirror `PasswordDialog` / `AboutDialog` / the drawer sections). Reuse, don't reinvent.
- Commit after every task. Pushing is the owner's call; do not push unless asked.

---

## Task 1: Dependencies & version bump

**Files:**
- Modify: `pyproject.toml` (deps, version, extras, classifiers, description)
- Modify: `pdfconv/__init__.py` (runtime `__version__` string)
- Modify: `requirements.txt` (keep in sync)

**Interfaces:**
- Produces: `markitdown`, `mcp` (extra), `openai` (extra) importable; `pdfconv` version `2.0.0` (both the packaging `[project].version` and the runtime `pdfconv.__version__`).

- [ ] **Step 1: Add markitdown to core deps + version bump in `pyproject.toml`**

In `[project]` set `version = "2.0.0"` and broaden `description`:
```toml
version = "2.0.0"
description = "Universal document -> Markdown converter (powered by Microsoft markitdown) plus PDF -> Word, with GUI, CLI, and an MCP server for AI agents."
```
In `[project].dependencies` add (keep the existing four):
```toml
    "markitdown[all]>=0.1,<0.2",
```
In `[project.optional-dependencies]` add:
```toml
mcp = ["mcp>=1.10,<2"]
llm = ["openai>=1.0"]
```
Add the MCP console script under `[project.scripts]`:
```toml
pdf2docx-mcp = "pdfconv.mcp_server:main"
```
(Keep `pdf2docx` and `pdf2docx-gui`. Note: spec §7 calls it `pdfconv-mcp`; use `pdf2docx-mcp` to stay consistent with the existing `pdf2docx*` script family — either is acceptable, pick one and use it in docs.)

- [ ] **Step 2: Bump the runtime version in `pdfconv/__init__.py`**

`pyproject.toml`'s `[project].version` is packaging metadata; the string every user-facing surface actually reads is `pdfconv.__version__` (cli.py argparse `version=f"%(prog)s {__version__}"`, gui.py AboutDialog/header `f"Version {__version__}"`, the settings drawer `f"PDF Converter v{__version__}"`, and the startup log). Bump it to match:
```python
__version__ = "2.0.0"
```
(Replace the existing `__version__ = "1.0.0"` line. Without this, `pdf2docx_app.py --version` still prints `1.0.0` and the Task 6 / Final-verification `--version → 2.0.0` checks fail.)

- [ ] **Step 3: Sync `requirements.txt`**

Add under the core deps block:
```
markitdown[all]>=0.1,<0.2   # any document -> Markdown (Microsoft); pulls a large dep tree
```
Add to the optional/extras comment block:
```
# mcp>=1.10,<2        # MCP server for AI agents (pip install .[mcp])
# openai>=1.0         # optional LLM image captions (pip install .[llm])
```

- [ ] **Step 4: Install and verify the import**

Run: `./.venv/Scripts/python.exe -m pip install -e ".[mcp,llm]"`
Then: `./.venv/Scripts/python.exe -c "import markitdown, mcp, openai; from markitdown import MarkItDown; print('deps OK')"`
Expected: `deps OK` (install is large; allow time. If the `azure-ai-contentunderstanding` beta fails to resolve, record the exact error and report — it is a known caveat.)

- [ ] **Step 5: Validate pyproject parses + runtime version**

Run: `./.venv/Scripts/python.exe -c "import tomllib; d=tomllib.load(open('pyproject.toml','rb')); print(d['project']['version'], list(d['project']['optional-dependencies']))"`
Expected: `2.0.0 ['dnd', 'ocr', 'dev', 'mcp', 'llm']`
Run: `./.venv/Scripts/python.exe -c "import pdfconv; print(pdfconv.__version__)"`
Expected: `2.0.0`

- [ ] **Step 6: Commit**

```bash
git add pyproject.toml pdfconv/__init__.py requirements.txt
git commit -m "build: add markitdown[all] + mcp/llm extras, bump to 2.0.0"
```

---

## Task 2: Engine — formats, discovery, probe, statuses, NoTextError

**Files:**
- Modify: `pdfconv/engine.py` (status constants, `SUPPORTED_EXTENSIONS`, `NoTextError`, `discover_files`, `probe_file`)
- Test: `tests/test_engine.py`

**Interfaces:**
- Produces:
  - `engine.SKIPPED = "skipped"` (status constant)
  - `engine.SUPPORTED_EXTENSIONS: frozenset[str]` (lowercase, dotted, e.g. `".pdf"`)
  - `engine.NoTextError(Exception)`
  - `engine.discover_files(path: Path, recursive: bool=True) -> list[Path]`
  - `engine.probe_file(path: str) -> PdfInfo` (PDF → real probe; non-PDF → `PdfInfo(pages=0, has_text=True, encrypted=False, error=None)`)
- Consumes: existing `PdfInfo`, `probe_pdf`, `discover_pdfs`.

- [ ] **Step 1: Write failing tests**

Add to `tests/test_engine.py`:
```python
def test_supported_extensions_membership():
    assert ".pdf" in engine.SUPPORTED_EXTENSIONS
    assert ".docx" in engine.SUPPORTED_EXTENSIONS
    assert ".xls" in engine.SUPPORTED_EXTENSIONS          # has an xls converter
    assert ".doc" not in engine.SUPPORTED_EXTENSIONS      # legacy, no converter
    assert ".ppt" not in engine.SUPPORTED_EXTENSIONS
    assert ".mp3" not in engine.SUPPORTED_EXTENSIONS      # audio dropped
    assert all(e == e.lower() and e.startswith(".") for e in engine.SUPPORTED_EXTENSIONS)


def test_skipped_status_exists():
    assert engine.SKIPPED == "skipped"


def test_discover_files_finds_mixed_types(tmp_path):
    (tmp_path / "a.pdf").write_bytes(b"%PDF-1.4")
    (tmp_path / "b.docx").write_bytes(b"PK")
    (tmp_path / "c.txt").write_text("hi", encoding="utf-8")
    (tmp_path / "skip.doc").write_bytes(b"x")        # excluded
    (tmp_path / "note.bin").write_bytes(b"x")        # unsupported
    found = {p.name for p in engine.discover_files(tmp_path, recursive=True)}
    assert found == {"a.pdf", "b.docx", "c.txt"}


def test_probe_file_nonpdf_is_ready(tmp_path):
    f = tmp_path / "x.docx"
    f.write_bytes(b"PK")
    info = engine.probe_file(str(f))
    assert info.error is None and info.has_text is True and info.encrypted is False and info.pages == 0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `./.venv/Scripts/python.exe -m pytest tests/test_engine.py -k "supported_extensions or skipped_status or discover_files or probe_file_nonpdf" -v`
Expected: FAIL (AttributeError: module has no attribute `SKIPPED`/`SUPPORTED_EXTENSIONS`/`discover_files`/`probe_file`).

- [ ] **Step 3: Implement in `engine.py`**

After the existing status constants block (after `ENCRYPTED = "encrypted"`), add:
```python
SKIPPED = "skipped"        # not applicable for the chosen output (e.g. non-PDF + DOCX)
```
After `SUPPORTED_FORMATS = ("docx", "md")`, add:
```python
# Input types we accept. Markdown output works for all of these (via markitdown);
# DOCX output is PDF-only. Audio/video and legacy .doc/.ppt are intentionally absent
# (see the v2.0 spec). Lock this against the installed markitdown converters' accepts().
SUPPORTED_EXTENSIONS = frozenset({
    ".pdf",
    ".docx", ".pptx", ".xlsx", ".xls",
    ".html", ".htm", ".csv", ".json", ".xml", ".txt", ".md", ".epub",
    ".zip", ".msg",
    ".jpg", ".jpeg", ".png", ".gif", ".bmp", ".tiff", ".webp",
})


class NoTextError(Exception):
    """Raised when a conversion yields empty/whitespace-only Markdown.

    Lets the file path map it to NOTEXT (no file written) and the inline MCP
    path propagate it so the agent gets an explicit error instead of empty text.
    """
```
Add `probe_file` next to `probe_pdf`:
```python
def probe_file(path: str) -> PdfInfo:
    """Probe any supported input. PDFs get the full pages/text/encryption probe;
    non-PDFs resolve to a 'ready' PdfInfo (has_text=True so the GUI maps them to
    QUEUED, not NOTEXT). markitdown reports its own per-file errors at convert time.
    """
    if Path(path).suffix.lower() == ".pdf":
        return probe_pdf(path)
    return PdfInfo(pages=0, has_text=True, encrypted=False, error=None)
```
Add `discover_files` next to `discover_pdfs` (keep `discover_pdfs` for now; it is removed when its last caller is gone — see Tasks 6/7):
```python
def discover_files(path: Path, recursive: bool = True) -> list[Path]:
    """Return sorted supported files under *path* (or just *path* if it's a file)."""
    path = Path(path)
    if path.is_file():
        return [path] if path.suffix.lower() in SUPPORTED_EXTENSIONS else []
    pattern = "**/*" if recursive else "*"
    return sorted(
        p for p in path.glob(pattern)
        if p.is_file() and p.suffix.lower() in SUPPORTED_EXTENSIONS
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `./.venv/Scripts/python.exe -m pytest tests/test_engine.py -k "supported_extensions or skipped_status or discover_files or probe_file_nonpdf" -v`
Expected: PASS (4 passed).

- [ ] **Step 5: Commit**

```bash
git add pdfconv/engine.py tests/test_engine.py
git commit -m "feat(engine): SUPPORTED_EXTENSIONS, discover_files, probe_file, SKIPPED, NoTextError"
```

---

## Task 3: Engine — markitdown conversion helper + empty-output guard

**Files:**
- Modify: `pdfconv/engine.py` (`_build_llm_client`, `markitdown_text`, `_convert_markitdown`)
- Test: `tests/test_engine.py`

**Interfaces:**
- Consumes: `_atomic_write`, `NoTextError`, `NOTEXT`.
- Produces:
  - `markitdown_text(src, *, llm_api_key="", llm_model="", llm_base_url="") -> str` (raises `NoTextError` on empty)
  - `_convert_markitdown(src, dst, *, llm_api_key="", llm_model="", llm_base_url="") -> dict | None` (returns a `result(NOTEXT, ...)` dict on empty; writes file + returns None on success)
  - `_build_llm_client(llm_api_key, llm_base_url) -> client | None`

- [ ] **Step 1: Write failing tests**

Add to `tests/test_engine.py` (uses the existing `_make_pdf`/`_task` helpers; add a docx maker and a blank-PNG maker — `fitz` is already imported at the top of the test file):
```python
def _make_docx(path, text="Hello DOCX"):
    from docx import Document          # python-docx ships with pdf2docx
    d = Document(); d.add_paragraph(text); d.save(str(path))
    return path


def _make_blank_png(path, w=16, h=16):
    # A solid-white, text-less, EXIF-free PNG via PyMuPDF (no PIL dependency).
    # With no llm_client (captioning off) markitdown yields no extractable text.
    pix = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, w, h))
    pix.clear_with(255)
    pix.save(str(path))
    return path


def test_markitdown_text_extracts(tmp_path):
    src = _make_docx(tmp_path / "a.docx", "Hello Markitdown")
    out = engine.markitdown_text(src)
    assert "Hello Markitdown" in out


def test_markitdown_text_empty_raises(tmp_path):
    empty = tmp_path / "empty.txt"
    empty.write_text("   \n\t ", encoding="utf-8")
    import pytest
    with pytest.raises(engine.NoTextError):
        engine.markitdown_text(empty)


def test_convert_markitdown_writes_md(tmp_path):
    src = _make_docx(tmp_path / "a.docx", "Body text here")
    dst = tmp_path / "a.md"
    res = engine._convert_markitdown(src, dst)
    assert res is None and dst.exists() and "Body text here" in dst.read_text(encoding="utf-8")


def test_convert_markitdown_empty_no_file(tmp_path):
    empty = tmp_path / "empty.txt"; empty.write_text("", encoding="utf-8")
    dst = tmp_path / "empty.md"
    res = engine._convert_markitdown(empty, dst)
    assert res is not None and res["status"] == engine.NOTEXT and not dst.exists()


def test_convert_markitdown_blank_png_notext(tmp_path):
    # spec §9 empty-output guard: a text-less image (captioning off) -> NOTEXT, no file.
    src = _make_blank_png(tmp_path / "blank.png")
    dst = tmp_path / "blank.md"
    res = engine._convert_markitdown(src, dst)
    assert res is not None and res["status"] == engine.NOTEXT and not dst.exists()
```

- [ ] **Step 2: Run to verify fail**

Run: `./.venv/Scripts/python.exe -m pytest tests/test_engine.py -k markitdown -v`
Expected: FAIL (no attribute `markitdown_text` / `_convert_markitdown`).

- [ ] **Step 3: Implement in `engine.py`**

Add (place near the conversion primitives, before `convert_one`):
```python
def _build_llm_client(llm_api_key: str, llm_base_url: str):
    """Build an OpenAI client for markitdown image captions, or None if no key."""
    if not llm_api_key:
        return None
    try:
        from openai import OpenAI
    except Exception:
        return None  # [llm] extra not installed -> captioning unavailable (off)
    return OpenAI(api_key=llm_api_key, base_url=(llm_base_url or None))


def markitdown_text(src, *, llm_api_key: str = "", llm_model: str = "",
                    llm_base_url: str = "") -> str:
    """Convert *src* to Markdown text. Raises NoTextError on empty output."""
    from markitdown import MarkItDown  # lazy: keep worker import cheap / spawn-safe

    client = _build_llm_client(llm_api_key, llm_base_url)
    md = MarkItDown(
        enable_plugins=False,
        llm_client=client,
        llm_model=((llm_model or "gpt-4o") if client else None),
    )
    result = md.convert(str(src))
    text = getattr(result, "markdown", None) or getattr(result, "text_content", "")
    if not text or not text.strip():
        raise NoTextError(
            "No extractable text (scanned/empty/image-only). For scanned PDFs enable "
            "OCR; for images, configure LLM captions."
        )
    return text.rstrip() + "\n"


def _convert_markitdown(src, dst, *, llm_api_key: str = "", llm_model: str = "",
                        llm_base_url: str = ""):
    """Write markitdown output atomically. Returns a NOTEXT result dict on empty
    (no file written); returns None on success."""
    try:
        text = markitdown_text(src, llm_api_key=llm_api_key, llm_model=llm_model,
                               llm_base_url=llm_base_url)
    except NoTextError as exc:
        return {"status": NOTEXT, "message": str(exc)}
    _atomic_write(Path(dst), lambda tmp: tmp.write_text(text, encoding="utf-8"))
    return None
```
(Note: `_convert_markitdown` returns a partial dict; `convert_one` wraps it into the full `result(...)` shape in Task 4.)

- [ ] **Step 4: Run to verify pass**

Run: `./.venv/Scripts/python.exe -m pytest tests/test_engine.py -k markitdown -v`
Expected: PASS (5 passed). If `_make_docx` import fails, install python-docx is already present via pdf2docx; verify with `./.venv/Scripts/python.exe -c "import docx; print('ok')"`.

- [ ] **Step 5: Commit**

```bash
git add pdfconv/engine.py tests/test_engine.py
git commit -m "feat(engine): markitdown_text + _convert_markitdown with empty-output guard"
```

---

## Task 4: Engine — `convert_one` control-flow restructure

**Files:**
- Modify: `pdfconv/engine.py` (`convert_one` body + task-contract docstring)
- Test: `tests/test_engine.py`

**Interfaces:**
- Consumes: `_convert_markitdown`, `_convert_docx`, decrypt/OCR helpers, `SKIPPED`, `SUPPORTED_EXTENSIONS`.
- Produces: `convert_one(task)` routing — non-PDF+md → markitdown; non-PDF+docx → `SKIPPED`; PDF keeps decrypt/OCR preamble then routes to markitdown (md) or pdf2docx (docx); task dict gains `llm_api_key`/`llm_model`/`llm_base_url` (empty defaults).

- [ ] **Step 1: Write failing tests**

```python
def test_nonpdf_to_md(tmp_path):
    src = _make_docx(tmp_path / "a.docx", "Routed via markitdown")
    res = engine.convert_one(_task(src, tmp_path / "a.md", "md"))
    assert res["status"] == engine.DONE
    assert "Routed via markitdown" in (tmp_path / "a.md").read_text(encoding="utf-8")


def test_nonpdf_to_docx_skipped(tmp_path):
    src = _make_docx(tmp_path / "a.docx")
    res = engine.convert_one(_task(src, tmp_path / "a.docx.docx", "docx"))
    assert res["status"] == engine.SKIPPED
    assert "PDF-only" in res["message"]


def test_pdf_to_md_via_markitdown(tmp_path):
    src = _make_pdf(tmp_path / "a.pdf", text="Pdf markitdown body")
    res = engine.convert_one(_task(src, tmp_path / "a.md", "md"))
    assert res["status"] == engine.DONE
    assert "Pdf markitdown body" in (tmp_path / "a.md").read_text(encoding="utf-8")


def test_encrypted_pdf_to_md_with_password(tmp_path):
    src = _make_pdf(tmp_path / "enc.pdf", text="secret body", encrypt="s3cret")
    res = engine.convert_one(_task(src, tmp_path / "enc.md", "md", password="s3cret"))
    assert res["status"] == engine.DONE
    assert "secret body" in (tmp_path / "enc.md").read_text(encoding="utf-8")


def test_pdf_to_md_ignores_out_of_range_start(tmp_path):
    # spec §3.1/§5: page range applies to PDF->DOCX only; for md output a stale
    # out-of-range start is ignored (NOT a FAILED). The GUI greys but still
    # carries start/end on the task dict, so the engine must not honour them.
    src = _make_pdf(tmp_path / "a.pdf", text="Whole doc body", pages=2)
    res = engine.convert_one(_task(src, tmp_path / "a.md", "md", start=99))
    assert res["status"] == engine.DONE
    assert "Whole doc body" in (tmp_path / "a.md").read_text(encoding="utf-8")
```

- [ ] **Step 2: Run to verify fail**

Run: `./.venv/Scripts/python.exe -m pytest tests/test_engine.py -k "nonpdf or pdf_to_md or encrypted_pdf_to_md or out_of_range" -v`
Expected: FAIL (non-PDF hits `fitz.open` → FAILED; or SKIPPED not returned; or — with today's pre-routing guard — PDF→md with `start=99` returns FAILED instead of DONE).

- [ ] **Step 3: Restructure `convert_one`**

Replace the body of `convert_one` (from after the `result()` helper definition through the conversion routing) so the type branch happens first. The new shape:
```python
    fid = task.get("id")
    src = Path(task["src"])
    dst = Path(task["dst"])
    fmt = task.get("fmt", "docx")
    start = task.get("start")
    end = task.get("end")
    ocr = bool(task.get("ocr"))
    password = task.get("password")
    llm_api_key = task.get("llm_api_key", "")
    llm_model = task.get("llm_model", "")
    llm_base_url = task.get("llm_base_url", "")
    t0 = time.perf_counter()

    def result(status: str, message: str = "") -> dict:
        return {"id": fid, "status": status, "message": message,
                "duration": time.perf_counter() - t0, "dst": str(dst)}

    if not src.exists():
        return result(FAILED, "Source file no longer exists.")

    ext = src.suffix.lower()

    # --- Non-PDF inputs: Markdown via markitdown; DOCX is unsupported -------
    if ext != ".pdf":
        if fmt == "docx":
            return result(SKIPPED, "DOCX output is PDF-only — choose Markdown.")
        try:
            r = _convert_markitdown(src, dst, llm_api_key=llm_api_key,
                                    llm_model=llm_model, llm_base_url=llm_base_url)
        except Exception as exc:  # noqa: BLE001
            return result(FAILED, f"{type(exc).__name__}: {exc}")
        if r is not None:
            return result(r["status"], r["message"])
        return result(DONE)

    # --- PDF inputs: decrypt/probe/OCR preamble, then route ----------------
    tmp_decrypted = None
    tmp_ocr = None
    try:
        import fitz  # PyMuPDF
    except Exception as exc:  # pragma: no cover
        return result(FAILED, f"PyMuPDF (fitz) not available: {exc}")
    try:
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

        doc = fitz.open(str(work_path))
        try:
            has_text = _has_text_layer(doc)
            page_count = doc.page_count
        finally:
            doc.close()

        if not has_text:
            if ocr:
                tmp_ocr = _run_ocr(work_path)
                if tmp_ocr is None:
                    return result(NOTEXT, "Scanned PDF and OCR tooling (ocrmypdf) is "
                                          "not installed — install it or convert a "
                                          "text-based PDF.")
                work_path = Path(tmp_ocr)
            else:
                return result(NOTEXT, "No text layer (scanned image). Enable OCR or "
                                      "convert a text-based PDF.")

        if fmt == "docx":
            # Page range applies to PDF->DOCX only (spec §3.1/§5). The out-of-range
            # FAILED guard therefore lives here, inside the docx branch — it must
            # NOT fire for md output, where any range is ignored (the GUI greys the
            # Pages strip but still carries the entered start/end on the task dict).
            if start is not None and page_count and start >= page_count:
                return result(FAILED,
                              f"Start page {start} is past the last page (document has "
                              f"{page_count} page(s), 0-indexed).")
            _convert_docx(work_path, dst, start, end)
            return result(DONE)
        elif fmt == "md":
            # start/end are intentionally ignored for Markdown (spec §3.1): no
            # out-of-range guard, no page slicing — markitdown converts the whole
            # (decrypted/OCR'd) document.
            r = _convert_markitdown(work_path, dst, llm_api_key=llm_api_key,
                                    llm_model=llm_model, llm_base_url=llm_base_url)
            if r is not None:
                return result(r["status"], r["message"])
            return result(DONE)
        else:
            return result(FAILED, f"Unsupported format: {fmt!r}")
    except Exception as exc:  # noqa: BLE001 - isolate every failure
        return result(FAILED, f"{type(exc).__name__}: {exc}")
    finally:
        for tmp in (tmp_decrypted, tmp_ocr):
            if tmp:
                try:
                    os.unlink(tmp)
                except OSError:
                    pass
```
Also update the `convert_one` docstring's "Expected task keys" line to add `llm_api_key`, `llm_model`, `llm_base_url`, and note the `SKIPPED` status.

- [ ] **Step 4: Run the full engine suite**

Run: `./.venv/Scripts/python.exe -m pytest tests/test_engine.py -v`
Expected: PASS, including the existing `test_convert_docx_*`, `test_encrypted_pdf_reported_then_unlocked`, `test_corrupt_pdf_is_isolated`, `test_page_range_past_end_fails_clearly` (it uses `fmt="docx"`, so the out-of-range guard — now inside the docx branch — still fires), the new `test_pdf_to_md_ignores_out_of_range_start` (md ignores the range), and the other new Task 3/4 tests. (The old `test_convert_markdown_contains_text` is updated in Task 11.)

- [ ] **Step 5: Commit**

```bash
git add pdfconv/engine.py tests/test_engine.py
git commit -m "feat(engine): type-branched convert_one (markitdown md path, PDF-only docx skip)"
```

---

## Task 5: Engine — remove dead bespoke-Markdown code

**Files:**
- Modify: `pdfconv/engine.py` (delete `_convert_markdown`, `_page_to_markdown`, `_table_to_markdown`, `_format_block`, `fitz_rect`, `_inside_any`, and `import statistics`)

**Interfaces:**
- Consumes: nothing new. Produces: a smaller engine; no public API change (these were all private/unused after Task 4).

- [ ] **Step 1: Confirm no remaining references**

Run: `./.venv/Scripts/python.exe - <<'PY'
import re, pathlib
src = pathlib.Path("pdfconv/engine.py").read_text(encoding="utf-8")
for name in ["_convert_markdown","_page_to_markdown","_table_to_markdown","_format_block","fitz_rect","_inside_any"]:
    print(name, src.count(name))
PY`
Expected: each name appears exactly at its definition (count reflects only def + internal cross-refs among the to-be-deleted block). Grep the rest of the repo: `grep -rn "_convert_markdown\|_page_to_markdown\|_table_to_markdown\|_format_block\|fitz_rect\|_inside_any" pdfconv tests` → only matches inside the block being removed (and the old md test, replaced in Task 11).

- [ ] **Step 2: Delete the dead functions and the unused import**

Remove the six functions listed above (the contiguous bespoke-Markdown block) and the `import statistics` line at the top of `engine.py`.

- [ ] **Step 3: Verify compile + suite still green**

Run: `./.venv/Scripts/python.exe -m py_compile pdfconv/engine.py && ./.venv/Scripts/python.exe -m pytest tests/test_engine.py -v`
Expected: compiles; all engine tests pass (the markitdown path replaced the bespoke one).

- [ ] **Step 4: Commit**

```bash
git add pdfconv/engine.py
git commit -m "refactor(engine): remove bespoke PyMuPDF Markdown extractor (superseded by markitdown)"
```

---

## Task 6: CLI — multi-format discovery, default `md`, skip pipeline

**Files:**
- Modify: `pdfconv/cli.py` (`build_parser`, `run`)
- Test: `tests/test_cli.py` (new)

**Interfaces:**
- Consumes: `engine.discover_files`, `engine.SKIPPED`.
- Produces: CLI accepting any supported input; `--format` default `md`; pre-task skip of non-PDF+docx with reconciled counters.

- [ ] **Step 1: Write failing tests** (`tests/test_cli.py`)

```python
from pathlib import Path
from pdfconv import cli, engine
from docx import Document


def _docx(p, t="hello"):
    d = Document(); d.add_paragraph(t); d.save(str(p)); return p


def test_default_format_is_md():
    args = cli.build_parser().parse_args(["--input", "x"])
    assert args.format == "md"


def test_cli_converts_docx_to_md(tmp_path, capsys):
    _docx(tmp_path / "a.docx", "cli body")
    rc = cli.run(["--input", str(tmp_path), "--output", str(tmp_path / "out")])
    assert rc == 0
    assert (tmp_path / "out" / "a.md").exists()


def test_cli_skips_nonpdf_docx(tmp_path, capsys):
    _docx(tmp_path / "a.docx")
    rc = cli.run(["--input", str(tmp_path), "--output", str(tmp_path / "out"),
                  "--format", "docx"])
    out = capsys.readouterr().out
    assert "SKIP" in out and "1 skipped" in out
    assert rc == 0
```

- [ ] **Step 2: Run to verify fail**

Run: `./.venv/Scripts/python.exe -m pytest tests/test_cli.py -v`
Expected: FAIL (default is `docx`; discover_files not used; no skip handling).

- [ ] **Step 3: Edit `build_parser`**

Change the `--format` line to default `md`:
```python
    p.add_argument("--format", choices=engine.SUPPORTED_FORMATS, default="md",
                   help="Output format: md (default, any input) or docx (PDF only).")
```
Update `--input` help to "A supported file or a folder of files." and the `--start/--end` help to note "PDF→DOCX only".

- [ ] **Step 4: Edit `run`**

- Replace `engine.discover_pdfs(in_path, recursive=args.recursive)` with `engine.discover_files(in_path, recursive=args.recursive)`; change the "no .pdf files found" message to "no supported files found in {in_path}".
- After computing `tasks` but before the executor, add `llm_*` empty defaults to each task dict (so the contract matches the engine): in the task dict literal add `"llm_api_key": "", "llm_model": "", "llm_base_url": "",`.
- Implement the pre-task skip + counter reconciliation. Replace the task-building loop and counter setup with:
```python
    tasks = []
    pre_skipped = 0
    if args.format == "md" and (args.start is not None or args.end is not None):
        print("note: page ranges apply to PDF->DOCX only; ignored for Markdown.",
              file=sys.stderr)
    for i, src in enumerate(pdfs):
        if args.format == "docx" and src.suffix.lower() != ".pdf":
            pre_skipped += 1
            print(f"SKIP  {src.name}  DOCX output is PDF-only — choose Markdown")
            continue
        dst = engine.resolve_output_path(
            src, args.format, output_mode, out_dir,
            mirror_root=mirror_root, prefix=args.prefix, suffix=args.suffix,
            overwrite=args.overwrite)
        tasks.append({
            "id": i, "src": str(src), "dst": str(dst), "fmt": args.format,
            "start": args.start, "end": args.end, "overwrite": args.overwrite,
            "ocr": args.ocr, "password": args.password,
            "llm_api_key": "", "llm_model": "", "llm_base_url": "",
        })

    total = len(tasks) + pre_skipped
    print(f"Converting {len(tasks)} file(s) to {args.format.upper()} with {workers} worker(s)…")
    ok = fail = 0
    skip = pre_skipped
    done = 0
```
- In the results loop's status mapping, add `SKIPPED` to the skip branch:
```python
            elif status in (engine.NOTEXT, engine.ENCRYPTED, engine.SKIPPED):
                skip += 1
                tag, detail = "SKIP ", res.get("message", "")
```
- No separate empty-`tasks` guard is needed. The early "no files" error stays gated on the existing `if not pdfs:` check (i.e. `discover_files` found nothing at all). For an all-skipped folder `pdfs` is non-empty, so the existing executor block runs with an empty future set: `future_to_task` is `{}`, the `as_completed` loop no-ops, and — because `skip` is seeded to `pre_skipped` and `total = len(tasks) + pre_skipped` — the final line prints `Done: 0 succeeded · 0 failed · N skipped` and `run` returns `0` (no `fail`). Do **not** add an `if not tasks:` branch that prints the summary, or it will print twice. (`workers = max(1, min(workers, len(pdfs)))` keeps `max_workers >= 1` even when every file is pre-skipped, so the pool constructs fine with no submitted tasks.)

- [ ] **Step 5: Run to verify pass**

Run: `./.venv/Scripts/python.exe -m pytest tests/test_cli.py -v`
Expected: PASS (3 passed). Also: `./.venv/Scripts/python.exe pdf2docx_app.py --version` still prints `pdf2docx_app 2.0.0`.

- [ ] **Step 6: Commit**

```bash
git add pdfconv/cli.py tests/test_cli.py
git commit -m "feat(cli): multi-format discovery, --format default md, non-PDF+docx skip"
```

---

## Task 7: GUI — ingress gates, probe routing & copy (make new formats reachable)

**Files:**
- Modify: `pdfconv/gui.py` (`add_files`, `_add_paths`, `add_folder`, `_on_drop`, `_probe_async`, drop-overlay/empty-state copy)

**Interfaces:**
- Consumes: `engine.SUPPORTED_EXTENSIONS`, `engine.discover_files`, `engine.probe_file`.
- Produces: GUI accepts all supported types from picker / folder / drag-drop, and probes them correctly (non-PDFs resolve to `QUEUED`, not `FAILED`/`NOTEXT`).

- [ ] **Step 1: Add headless ingress + probe-routing tests** (`tests/test_gui_ingress.py`)

```python
import os
os.environ["PDFCONV_REDUCED_MOTION"] = "1"
import queue as _queue
from pathlib import Path
from docx import Document
from pdfconv import engine


def test_add_paths_accepts_supported(tmp_path):
    import pdfconv.gui as gui
    app = gui.App()
    try:
        Document().save(str(tmp_path / "a.docx"))
        (tmp_path / "b.txt").write_text("hi", encoding="utf-8")
        (tmp_path / "c.bin").write_bytes(b"x")
        app._add_paths([tmp_path / "a.docx", tmp_path / "b.txt", tmp_path / "c.bin"])
        names = {it.name for it in app.items}
        assert names == {"a.docx", "b.txt"}      # .bin rejected, others accepted
    finally:
        app.destroy()


def _drain_probes(app, expected, timeout=10.0):
    """Pull `expected` probe events off the queue (the probe runs on a daemon
    thread) and apply each via `_handle_event`, so item.status reflects the probe."""
    import time
    applied = 0
    deadline = time.monotonic() + timeout
    while applied < expected and time.monotonic() < deadline:
        try:
            evt = app.event_queue.get(timeout=0.2)
        except _queue.Empty:
            continue
        if evt[0] == "probe":
            app._handle_event(evt)
            applied += 1
    assert applied == expected, f"only {applied}/{expected} probe events arrived"


def test_nonpdf_probes_to_queued(tmp_path):
    """A .docx and a .csv must probe to QUEUED via engine.probe_file — NOT
    FAILED (probe_pdf errors on a .csv) or NOTEXT (probe_pdf sees no text layer
    in a .docx). This guards the GUI ingress against the probe_pdf regression."""
    import pdfconv.gui as gui
    app = gui.App()
    try:
        Document().save(str(tmp_path / "a.docx"))
        (tmp_path / "b.csv").write_text("a,b\n1,2\n", encoding="utf-8")
        app._add_paths([tmp_path / "a.docx", tmp_path / "b.csv"])
        _drain_probes(app, expected=2)
        by_name = {it.name: it.status for it in app.items}
        assert by_name["a.docx"] == engine.QUEUED
        assert by_name["b.csv"] == engine.QUEUED
    finally:
        app.destroy()
```

- [ ] **Step 2: Run to verify fail**

Run: `PYTHONPATH='D:\pdftodocx' ./.venv/Scripts/python.exe -m pytest tests/test_gui_ingress.py -v`
Expected: FAIL — `test_add_paths_accepts_supported` because `_add_paths` drops non-`.pdf` (`names == set()`); `test_nonpdf_probes_to_queued` because `_probe_async` calls `engine.probe_pdf`, which makes the `.csv` resolve to `FAILED` (`info.error`) and the `.docx` to `NOTEXT` (`has_text=False`), not `QUEUED`.

- [ ] **Step 3: Edit the four gates + probe routing + copy in `gui.py`**

- `_probe_async` (currently `info = engine.probe_pdf(str(item.path))`): route through the type-aware probe so non-PDFs land on a ready `PdfInfo` instead of a `fitz.open` error / no-text-layer reading:
```python
                info = engine.probe_file(str(item.path))
```
  This is the consumer of `engine.probe_file` (Task 2) required by spec §3.4: `probe_pdf` errors on a `.csv` (→ `_handle_event` maps `info.error` to `engine.FAILED`) and reports `has_text=False` for a `.docx` (→ `engine.NOTEXT`); `probe_file` returns `PdfInfo(pages=0, has_text=True, encrypted=False, error=None)` for non-PDFs so `_handle_event` falls through to `engine.QUEUED`. Without this rewire, supported non-PDF rows show "Failed"/"No text" before any conversion and the Task 8 pre-skip (`item.status == engine.NOTEXT`) would wrongly skip valid `.docx`/`.txt`/`.csv` files queued for Markdown.
- `add_files` filetypes (currently `[("PDF files", "*.pdf")]`): replace with an all-supported group:
```python
        exts = " ".join(sorted("*" + e for e in engine.SUPPORTED_EXTENSIONS))
        paths = filedialog.askopenfilenames(
            title="Add files", initialdir=initial,
            filetypes=[("All supported files", exts), ("All files", "*.*")])
```
- `_add_paths` suffix check (currently `if p.suffix.lower() != ".pdf" or str(p) in existing:`): change to
```python
            if p.suffix.lower() not in engine.SUPPORTED_EXTENSIONS or str(p) in existing:
```
- `add_folder`: replace `engine.discover_pdfs(Path(folder), recursive=True)` with `engine.discover_files(Path(folder), recursive=True)`; change the warning text "No PDFs found in {folder}" → "No supported files found in {folder}".
- `_on_drop`: replace `engine.discover_pdfs(path, recursive=True)` with `engine.discover_files(...)`; change `elif path.suffix.lower() == ".pdf":` → `elif path.suffix.lower() in engine.SUPPORTED_EXTENSIONS:`.
- Copy: drop-overlay label "Drop PDFs to add to the queue" → "Drop files to add to the queue"; empty-state subtitle "Add PDFs or drop a folder here to start converting to DOCX or Markdown." → "Add files or drop a folder here to convert to Markdown or (for PDFs) Word."

- [ ] **Step 4: Run to verify pass**

Run: `PYTHONPATH='D:\pdftodocx' ./.venv/Scripts/python.exe -m pytest tests/test_gui_ingress.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add pdfconv/gui.py tests/test_gui_ingress.py
git commit -m "feat(gui): accept all supported input types + probe_file routing (picker, folder, drag-drop)"
```

---

## Task 8: GUI — SKIPPED wiring, pages label, page-range gating, DOCX hint

**Files:**
- Modify: `pdfconv/gui.py` (`_STATUS_DISPLAY`, `_pages_label`, `_start_run`, `_apply_result`, `start_convert`, `_on_format_select`, Pages strip widgets)

**Interfaces:**
- Consumes: `engine.SKIPPED`.
- Produces: skip handling end-to-end; file-type pages label; Pages strip greyed when format==md; non-PDF rows hint when DOCX selected.

- [ ] **Step 1: Add headless logic tests** (`tests/test_gui_logic.py`)

```python
import os
os.environ["PDFCONV_REDUCED_MOTION"] = "1"
from pathlib import Path
from docx import Document
import pdfconv.gui as gui
from pdfconv import engine


def test_pages_label_filetype_for_nonpdf():
    item = gui.FileItem(0, Path("x.docx"), 0, engine.QUEUED)
    assert gui._pages_label(item) == "DOCX"


def test_skipped_status_in_display():
    assert engine.SKIPPED in gui._STATUS_DISPLAY


def test_nonpdf_docx_preskipped(tmp_path):
    app = gui.App()
    try:
        Document().save(str(tmp_path / "a.docx"))
        app._add_paths([tmp_path / "a.docx"])
        app.cfg["format"] = "docx"
        item = app.items[0]
        app._start_run([item])
        assert item.status == engine.SKIPPED
        assert app.summary["skip"] == 1
    finally:
        app.destroy()
```

- [ ] **Step 2: Run to verify fail**

Run: `PYTHONPATH='D:\pdftodocx' ./.venv/Scripts/python.exe -m pytest tests/test_gui_logic.py -v`
Expected: FAIL.

- [ ] **Step 3: Implement the wiring**

- `_STATUS_DISPLAY`: add `engine.SKIPPED: ("Skipped", theme.ST_CONV),`.
- `_pages_label(item)`: at the top, return the file-type for non-PDFs:
```python
def _pages_label(item: FileItem) -> str:
    if item.path.suffix.lower() != ".pdf":
        return item.path.suffix.lstrip(".").upper()
    return f"{item.pages} pp" if item.pages else "—"
```
- `_start_run`: in the `candidates` loop, add a format-skip branch alongside the existing NOTEXT/ENCRYPTED pre-skips:
```python
            if Path(item.path).suffix.lower() != ".pdf" and fmt == "docx":
                pre_skipped += 1
                item.status = engine.SKIPPED
                if item.row:
                    item.row.refresh()
                self.audit_records.append({"source": str(item.path), "destination": "",
                                           "status": "skipped-format", "duration": 0.0})
                self.log(f"Skipped {item.name}: DOCX output is PDF-only.", "warn")
                continue
```
- `_apply_result`: add `SKIPPED` to the skip tally branch (`elif status in (engine.NOTEXT, engine.ENCRYPTED, engine.SKIPPED):`) and, in the audit append, remap the defensive engine SKIPPED to the audit string:
```python
        self.audit_records.append({
            "source": str(item.path) if item else "", "destination": dst,
            "status": "skipped-format" if status == engine.SKIPPED else status,
            "duration": res.get("duration", 0.0)})
```
- `start_convert`: add `engine.SKIPPED` to the `eligible` status set so a re-run re-evaluates skipped rows.
- Pages strip gating: in `_on_format_select(val)`, after setting `self.cfg["format"]`, enable/disable the Pages entries by format:
```python
        state = "disabled" if val == "md" else "normal"
        self.start_entry.configure(state=state)
        self.end_entry.configure(state=state)
```
Call the same enable/disable once at the end of `_build_options` to set the initial state from `self.cfg["format"]`. (Disabling preserves entered values per spec §5: `_start_run` still carries the entered `start`/`end` on every task dict, but the engine ignores them for `fmt == "md"` and only honours them in the docx branch — including the out-of-range FAILED guard, which is scoped to PDF→DOCX per spec §3.1, see Task 4. So a stale out-of-range value left over from a docx run never FAILs an md conversion.)
- DOCX non-PDF hint: in `FileRow.refresh`, when `self.app.cfg["format"] == "docx"` and the row's file is non-PDF, show a small hint in the status cell (e.g. set `self.status_lbl` text to "DOCX is PDF-only" muted) — minimal: reuse the existing status label styling. (Keep this lightweight; the authoritative skip happens in `_start_run`.)

- [ ] **Step 4: Run to verify pass**

Run: `PYTHONPATH='D:\pdftodocx' ./.venv/Scripts/python.exe -m pytest tests/test_gui_logic.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add pdfconv/gui.py tests/test_gui_logic.py
git commit -m "feat(gui): SKIPPED wiring, file-type pages label, page-range gating, DOCX hint"
```

---

## Task 9: GUI + config — optional LLM image-caption settings

**Files:**
- Modify: `pdfconv/config.py` (`DEFAULTS`), `pdfconv/gui.py` (settings drawer fields + task threading)

**Interfaces:**
- Consumes: `importlib.util.find_spec`.
- Produces: `config.DEFAULTS` gains `llm_api_key`/`llm_model`/`llm_base_url` (empty); GUI threads them onto each task dict; drawer exposes the fields (greyed if `openai` missing).

- [ ] **Step 1: Add config defaults**

In `config.DEFAULTS` add:
```python
    "llm_api_key": "",
    "llm_model": "",
    "llm_base_url": "",
```

- [ ] **Step 2: Thread keys onto GUI tasks**

In `_start_run`, where the task dict is built, add:
```python
                "llm_api_key": self.cfg.get("llm_api_key", ""),
                "llm_model": self.cfg.get("llm_model", ""),
                "llm_base_url": self.cfg.get("llm_base_url", ""),
```

- [ ] **Step 3: Add the drawer settings group**

In `SettingsDrawer._build`, add an "Image captions (optional)" section after Notifications, wired the **same way** as the existing prefix/suffix fields (`self.prefix_var`/`self.suffix_var` → `CTkEntry(textvariable=...)` → persisted in `close()`), so it stays consistent with the rest of the drawer. Use the existing `_section` / `_caption` / `_rule` builders and the existing entry styling (`fg_color=theme.BG`, `border_color=theme.BORDER`, `text_color=theme.TEXT`, `font=f.body`) — no ad-hoc styling (Global Constraint; Task 14 audits this).

- Create the three StringVars from `cfg` at build time:
```python
        self.llm_key_var = ctk.StringVar(value=cfg["llm_api_key"])
        self.llm_model_var = ctk.StringVar(value=cfg["llm_model"])
        self.llm_base_url_var = ctk.StringVar(value=cfg["llm_base_url"])
```
- Build the section and the three entries (API key field masked with `show="•"`); add captions via `_caption` (e.g. "Model defaults to gpt-4o" / "Optional OpenAI-compatible endpoint"):
```python
        self._section(body, "Image captions (optional)")
        # API key (masked), Model, Base URL — each a CTkLabel + CTkEntry, e.g.:
        ctk.CTkEntry(body, textvariable=self.llm_key_var, show="•", height=30,
                     fg_color=theme.BG, border_color=theme.BORDER,
                     text_color=theme.TEXT, font=f.body).pack(fill="x", padx=4)
        # ...model entry (textvariable=self.llm_model_var) and base-URL entry
        #    (textvariable=self.llm_base_url_var) the same way...
        self._rule(body)
```
- Persist them in `close()` alongside the other settings (mirroring `cfg["prefix"] = self.prefix_var.get()`):
```python
        cfg["llm_api_key"] = self.llm_key_var.get()
        cfg["llm_model"] = self.llm_model_var.get()
        cfg["llm_base_url"] = self.llm_base_url_var.get()
```
- At build, probe availability once (no eager `import openai`, keeping the import lazy per spec §3.5):
```python
        import importlib.util
        if importlib.util.find_spec("openai") is None:
            # disable the three entries (state="disabled") + add a _caption
            # "Install pdfconv[llm] to enable image captions"
```

- [ ] **Step 4: Verify compile + config round-trip**

Run: `./.venv/Scripts/python.exe -m py_compile pdfconv/gui.py pdfconv/config.py`
Run: `./.venv/Scripts/python.exe -c "from pdfconv import config; d=config.load(); assert 'llm_api_key' in d; print('config ok')"`
Expected: compiles; `config ok`.

- [ ] **Step 5: Commit**

```bash
git add pdfconv/gui.py pdfconv/config.py
git commit -m "feat(gui): optional LLM image-caption settings (off by default)"
```

---

## Task 10: GUI — MarkItAll branding (UI copy only)

**Files:**
- Modify: `pdfconv/gui.py` (window title, header subtitle, About dialog)

**Interfaces:** none (copy only; no identifier changes).

- [ ] **Step 1: Update copy**

- `self.title("PDF Converter")` → `self.title("MarkItAll")`.
- Header title label "PDF → DOCX · Markdown" → "MarkItAll"; subtitle "Convert PDFs to editable documents" → "Any document → Markdown · PDF → Word".
- `AboutDialog` title label "PDF → DOCX · Markdown" → "MarkItAll", and keep the version line (`__version__` now 2.0.0).

- [ ] **Step 2: Verify**

Run: `./.venv/Scripts/python.exe -m py_compile pdfconv/gui.py`
Expected: compiles.

- [ ] **Step 3: Commit**

```bash
git add pdfconv/gui.py
git commit -m "feat(gui): rebrand UI to MarkItAll (copy only)"
```

---

## Task 11: Update existing md test for markitdown output

**Files:**
- Modify: `tests/test_engine.py` (`test_convert_markdown_contains_text`, `_task` helper)

- [ ] **Step 1: Update `_task` helper** to include the new keys:
```python
    task = {"id": 0, "src": str(src), "dst": str(dst), "fmt": fmt,
            "start": None, "end": None, "overwrite": True, "ocr": False,
            "password": None, "llm_api_key": "", "llm_model": "", "llm_base_url": ""}
```

- [ ] **Step 2: Rewrite `test_convert_markdown_contains_text`** to assert markitdown output for a PDF:
```python
def test_convert_markdown_contains_text(tmp_path):
    src = _make_pdf(tmp_path / "a.pdf", text="Hello Markdown")
    dst = tmp_path / "a.md"
    res = engine.convert_one(_task(src, dst, "md"))
    assert res["status"] == engine.DONE
    assert "Hello Markdown" in dst.read_text(encoding="utf-8")
```

- [ ] **Step 3: Run the full suite**

Run: `./.venv/Scripts/python.exe -m pytest -v`
Expected: all pass (engine + cli + gui logic/ingress).

- [ ] **Step 4: Commit**

```bash
git add tests/test_engine.py
git commit -m "test: update md test for markitdown output + new task keys"
```

---

## Task 12: MCP server

**Files:**
- Create: `pdfconv/mcp_server.py`
- Test: `tests/test_mcp.py`

**Interfaces:**
- Consumes: `engine.markitdown_text`, `engine.convert_one`, `engine.resolve_output_path`, `engine.SUPPORTED_EXTENSIONS`, `engine.NoTextError`, `engine.DONE/SKIPPED`.
- Produces: `pdfconv.mcp_server.main()` (stdio server) + tools `convert_to_markdown`, `convert_file`, `list_supported_formats`.

- [ ] **Step 1: Write failing tests** (`tests/test_mcp.py`)

```python
from pathlib import Path
from docx import Document
import pytest
from pdfconv import mcp_server, engine


def test_list_formats():
    fmts = mcp_server.list_supported_formats()
    assert ".pdf" in fmts and ".docx" in fmts


def test_convert_to_markdown_inline(tmp_path):
    p = tmp_path / "a.docx"
    d = Document(); d.add_paragraph("inline md body"); d.save(str(p))
    assert "inline md body" in mcp_server.convert_to_markdown(str(p))


def test_convert_to_markdown_empty_raises(tmp_path):
    e = tmp_path / "e.txt"; e.write_text("", encoding="utf-8")
    with pytest.raises(Exception):
        mcp_server.convert_to_markdown(str(e))


def test_convert_file_docx_nonpdf_skips(tmp_path):
    p = tmp_path / "a.docx"; d = Document(); d.add_paragraph("x"); d.save(str(p))
    res = mcp_server.convert_file(str(p), output_format="docx",
                                  output_dir=str(tmp_path / "o"))
    assert res["status"] == engine.SKIPPED and res["output_path"] is None
```

- [ ] **Step 2: Run to verify fail**

Run: `./.venv/Scripts/python.exe -m pytest tests/test_mcp.py -v`
Expected: FAIL (no module `pdfconv.mcp_server`).

- [ ] **Step 3: Implement `pdfconv/mcp_server.py`**

```python
"""MCP server exposing the MarkItAll engine to AI agents over stdio.

SECURITY: runs with the user's privileges; tools read/write ARBITRARY paths.
Intended for local, trusted agents over stdio only. LLM captions and remote
fetch are OFF. See the spec §7.
"""
from __future__ import annotations

import logging
from pathlib import Path

from mcp.server.fastmcp import FastMCP

from . import engine, logsetup

log = logging.getLogger("pdfconv")
mcp = FastMCP("pdfconv")


@mcp.tool()
def list_supported_formats() -> list[str]:
    """Return the input file extensions this server can convert."""
    return sorted(engine.SUPPORTED_EXTENSIONS)


@mcp.tool()
def convert_to_markdown(path: str) -> str:
    """Convert a local file to Markdown and return it inline.

    Raises on empty/scanned/encrypted/unsupported input. Captioning is OFF.
    """
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"File not found: {path}")
    if p.suffix.lower() == ".pdf":
        import fitz
        doc = fitz.open(str(p))
        try:
            if doc.needs_pass:
                raise ValueError("Password required.")  # encrypted PDF, no pw via MCP
        finally:
            doc.close()
    return engine.markitdown_text(p)  # NoTextError propagates -> isError


@mcp.tool()
def convert_file(path: str, output_format: str = "md",
                 output_dir: str | None = None) -> dict:
    """Convert a file to a written .md or (PDF-only) .docx. Returns
    {status, message, output_path|null}. Raises on hard failure."""
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"File not found: {path}")
    if output_format not in engine.SUPPORTED_FORMATS:
        raise ValueError(f"output_format must be one of {engine.SUPPORTED_FORMATS}")
    if output_format == "docx" and p.suffix.lower() != ".pdf":
        return {"status": engine.SKIPPED,
                "message": "DOCX output is PDF-only — choose Markdown.",
                "output_path": None}
    out_dir = Path(output_dir) if output_dir else None
    dst = engine.resolve_output_path(
        p, output_format, "choose" if out_dir else "next", out_dir, overwrite=False)
    task = {"id": 0, "src": str(p), "dst": str(dst), "fmt": output_format,
            "start": None, "end": None, "overwrite": False, "ocr": False,
            "password": None, "llm_api_key": "", "llm_model": "", "llm_base_url": ""}
    res = engine.convert_one(task)
    status = res["status"]
    if status == engine.FAILED:
        raise RuntimeError(res.get("message", "conversion failed"))
    return {"status": status, "message": res.get("message", ""),
            "output_path": res.get("dst") if status == engine.DONE else None}


def main() -> None:
    # Logs go to file/stderr only — NEVER stdout (it is the MCP channel).
    logsetup.setup_logging()
    log.info("Starting pdfconv MCP server (stdio)")
    mcp.run()


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run to verify pass**

Run: `./.venv/Scripts/python.exe -m pytest tests/test_mcp.py -v`
Expected: PASS (4 passed). Also verify the server module starts and is importable: `./.venv/Scripts/python.exe -c "from pdfconv import mcp_server; print([t for t in ('convert_to_markdown','convert_file','list_supported_formats')])"`.

- [ ] **Step 5: Verify stdout cleanliness** (stdout is the MCP channel — it must stay silent)

Create `tests/_stdout_check.py`:
```python
import io
from contextlib import redirect_stdout
from pathlib import Path
from docx import Document
from pdfconv import mcp_server

p = Path("_tmp_chk.docx"); d = Document(); d.add_paragraph("hi"); d.save(str(p))
buf = io.StringIO()
with redirect_stdout(buf):
    mcp_server.convert_to_markdown(str(p))
p.unlink()
assert buf.getvalue() == "", f"stdout polluted: {buf.getvalue()!r}"
print("stdout clean")
```
Run: `./.venv/Scripts/python.exe tests/_stdout_check.py`
Expected: `stdout clean`. Then delete the scratch file: `rm tests/_stdout_check.py`.

- [ ] **Step 6: Commit**

```bash
git add pdfconv/mcp_server.py tests/test_mcp.py
git commit -m "feat(mcp): stdio MCP server (convert_to_markdown, convert_file, list_supported_formats)"
```

---

## Task 13: Docs — README, CHANGELOG, third-party, security

**Files:**
- Modify: `README.md`
- Create: `CHANGELOG.md`

- [ ] **Step 1: Rewrite README scope & formats**

Update the title/intro to "MarkItAll" and the universal scope. Replace the PDF-centric feature/quickstart wording. Add a **Supported formats** table (from `SUPPORTED_EXTENSIONS`), noting Markdown-for-all + DOCX-for-PDF-only, and that `.doc`/`.ppt` and audio/video/URLs are out of scope.

- [ ] **Step 2: Add install caveats**

Note `markitdown[all]` is a large install (onnxruntime/magika, pandas, Azure SDKs incl. the pre-release `azure-ai-contentunderstanding` beta — known caveat); audio/video deps are installed but unused; image captions need `pip install ".[llm]"` + an API key; ffmpeg is not required (audio dropped). Caveat the PyInstaller portable build (fragile with onnxruntime; full features via source/pip).

- [ ] **Step 3: Add MCP + SECURITY sections**

Document running our MCP server (`pdf2docx-mcp`, install `.[mcp]`) and a sample Claude Desktop/Code `mcpServers` config; document Microsoft's `markitdown-mcp` as the URL alternative (note both expose `convert_to_markdown`; ours takes a local `path`, theirs a `uri`). Add a **SECURITY** subsection mirroring the spec §7 posture (user privileges, arbitrary paths, local trusted stdio, captions/remote off).

- [ ] **Step 4: Update the third-party licenses table**

Add markitdown (MIT), magika/onnxruntime, pandas, mcp (MIT), openai (optional). State no new copyleft beyond the existing PyMuPDF AGPL.

- [ ] **Step 5: Create `CHANGELOG.md`**

```markdown
# Changelog

## 2.0.0 — 2026-06-23
### Added
- Convert any supported document to Markdown via Microsoft markitdown (Word, Excel,
  PowerPoint, HTML, CSV/JSON/XML, EPub, ZIP, Outlook .msg, images).
- MCP server (`pdf2docx-mcp`) exposing conversion to AI agents over stdio.
- Optional LLM image captions (`pip install ".[llm]"`, off by default).
### Changed
- CLI `--format` default is now `md` (was `docx`).
- PDF→Markdown now uses markitdown (replaces the bespoke PyMuPDF extractor).
- UI rebranded to "MarkItAll" (package/CLI names unchanged).
### Notes
- Audio/video transcription and URL/YouTube input are intentionally out of scope.
- DOCX output remains PDF-only; non-PDF + DOCX is skipped.
```

- [ ] **Step 6: Verify links/build & commit**

Run: `./.venv/Scripts/python.exe -m pytest -q` (final full suite green).
```bash
git add README.md CHANGELOG.md
git commit -m "docs: README v2 scope/MCP/security/caveats + CHANGELOG"
```

---

## Task 14: UI consistency pass

**Files:**
- Modify: `pdfconv/gui.py` (only if inconsistencies are found)
- Test: `tests/test_gui_consistency.py` (new)

**Interfaces:** none new — this task audits the GUI added in Tasks 7–10 against the design system (see the UI-consistency Global Constraint).

- [ ] **Step 1: Audit new GUI code for ad-hoc styling**

Review the v2 GUI diff and confirm no new hardcoded styling crept in:
Run: `git diff 8e45562 -- pdfconv/gui.py | grep -nE "#[0-9a-fA-F]{3,6}|family=|font=\(|size=[0-9]" || echo "no raw style literals in the diff"`
Expected: `no raw style literals in the diff` (added lines reference `theme.*`, `self.fonts.*`, `_icon(...)`, and the `_section/_caption/_rule/_switch` builders — not raw hex/font literals). If any appear, replace them with the matching token in Step 3.

- [ ] **Step 2: Add a programmatic token-consistency test** (`tests/test_gui_consistency.py`)

```python
import os
os.environ["PDFCONV_REDUCED_MOTION"] = "1"
from pathlib import Path
from docx import Document
import pdfconv.gui as gui
from pdfconv import engine, theme


def test_skip_family_status_colors_are_palette():
    # SKIPPED must use a real ST_* palette colour and group with the other skips.
    label, color = gui._STATUS_DISPLAY[engine.SKIPPED]
    assert color in (theme.ST_CONV, theme.ST_QUEUED, theme.ST_FAIL, theme.ST_DONE)
    assert color == gui._STATUS_DISPLAY[engine.ENCRYPTED][1]  # coherent with "Locked"


def test_about_dialog_uses_theme_and_fonts(tmp_path):
    app = gui.App()
    try:
        dlg = gui.AboutDialog(app, app.fonts)
        app.update_idletasks()
        # Title text rebranded; window bg is the theme token.
        assert dlg.cget("fg_color") == theme.BG or list(dlg.cget("fg_color")) == list(theme.BG)
        dlg.destroy()
    finally:
        app.destroy()


def test_window_title_rebranded():
    app = gui.App()
    try:
        assert app.title() == "MarkItAll"
    finally:
        app.destroy()
```

- [ ] **Step 3: Run; fix any inconsistency at its source**

Run: `PYTHONPATH='D:\pdftodocx' ./.venv/Scripts/python.exe -m pytest tests/test_gui_consistency.py -v`
Expected: PASS. If a check fails, fix the offending widget to use the theme token / font / builder (do not weaken the test), then re-run.

- [ ] **Step 4: Visual confirmation (real render)**

Render the app and screenshot each new/changed surface; eyeball against the design system. Write `tools/_ui_shot.py` that (with `PDFCONV_REDUCED_MOTION=1`) builds `App`, adds one `.pdf` + one `.docx` + one `.txt` to the queue, opens the settings drawer (Image-captions group visible), and uses `PIL.ImageGrab` to save window-region PNGs of: (a) the header (MarkItAll branding), (b) the queue (file-type labels in the Pages column; a non-PDF row's DOCX hint with format=docx; a Skipped row), (c) the settings drawer (captions group matching the other sections), (d) the About dialog. Read each PNG and confirm fonts, colors, spacing, and button styling match the rest of the app. (DPI note: customtkinter is DPI-aware; capture `winfo_rootx/y/width/height` and lift the window first, as in the v1 drawer-fix diagnostics.)

Fix any visual inconsistency at its source (theme token / font / builder), then delete the scratch script.

- [ ] **Step 5: Commit**

```bash
git add pdfconv/gui.py tests/test_gui_consistency.py
git commit -m "test(gui): UI consistency pass (design-system tokens, rebrand, skip-status palette)"
```

---

## Final verification (after all tasks)

- [ ] Full suite: `./.venv/Scripts/python.exe -m pytest -v` → all green.
- [ ] Byte-compile: `./.venv/Scripts/python.exe -m py_compile pdf2docx_app.py pdfconv/*.py pdf2docx_app.spec`.
- [ ] Manual smoke (real run): launch GUI, add a `.docx` + a `.pdf`, convert to Markdown; convert a PDF to DOCX; confirm a scanned/empty input shows "No text" (not an empty file).
- [ ] UI consistency (Task 14): new surfaces (captions group, file-type labels, Skipped rows, DOCX hint, MarkItAll header/About) visually match the slate-and-indigo system — fonts, colors, spacing, and button styling are indistinguishable from the existing UI.
- [ ] CLI: `pdf2docx_app.py --input <folder> --output out --format md` over a mixed folder; `--version` → 2.0.0.
- [ ] MCP: wire `pdf2docx-mcp` into a client (or run `mcp` dev inspector) and call `convert_to_markdown`.
