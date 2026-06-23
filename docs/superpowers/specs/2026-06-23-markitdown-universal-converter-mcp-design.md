# MarkItAll — Universal Document → Markdown Converter + MCP (v2.0) — Design

**Date:** 2026-06-23
**Status:** Approved decisions; spec under review
**Supersedes scope of:** the v1.0 PDF→DOCX/MD tool

## 1. Goal & scope

Grow the tool from "PDF → DOCX/MD" into **"any supported document → Markdown, plus PDF → Word,"**
powered by Microsoft **markitdown** for the Markdown path, and expose it to AI agents via an **MCP server**.

- **App UI name:** **MarkItAll** (subtitle: *"Any document → Markdown · PDF → Word"*). Package/repo stay `pdfconv`.
- **Version:** 2.0.0 (broadened scope, new MCP, CLI default change).
- **License:** stays **AGPL-3.0** (PyMuPDF still present via pdf2docx).

### Decisions (confirmed with owner)
1. **Additive**: keep PDF→DOCX (pdf2docx); add many-formats→Markdown (markitdown).
2. **Dependencies**: install `markitdown[all]` in **core** (owner's "everything" choice). MCP SDK (`mcp`) as a `[mcp]` extra.
3. **Audio/video: DROPPED** as input types (privacy: markitdown's transcription uploads audio to Google's Web Speech API). The `[all]` deps are still installed but those extensions are **not** in `SUPPORTED_EXTENSIONS`, so the network transcription path is never invoked. Re-enabling later is a one-line change.
4. **URLs/YouTube: out of scope** for v2.0 (file/folder pipeline only); README points to Microsoft's `markitdown-mcp` for URL conversion.
5. **MCP**: ship our own integrated server **and** document Microsoft's `markitdown-mcp`.

### Non-goals (v2.0)
- Audio/video transcription; URL/YouTube/stdin input; offline OCR of images (markitdown has no built-in image OCR — only EXIF + optional LLM captions).

## 2. Supported inputs

`SUPPORTED_EXTENSIONS` (single source of truth in `engine.py`, consumed by discovery, picker, drag-drop, probe routing, MCP):

- **Documents:** `.pdf .docx .doc .pptx .ppt .xlsx .xls`
- **Web/text:** `.html .htm .csv .json .xml .txt .md .epub`
- **Archive:** `.zip` (markitdown iterates contents)
- **Outlook:** `.msg`
- **Images:** `.jpg .jpeg .png .gif .bmp .tiff .webp` — EXIF metadata + **optional** LLM caption only (no OCR); text-less images resolve to `NOTEXT` (see §4).

**Output formats:** **Markdown** (all inputs) and **DOCX** (PDF input only, via pdf2docx).

## 3. Engine redesign (`engine.py`)

### 3.1 Control flow — the critical fix
`convert_one(task)` must **branch on input type before** the PyMuPDF/encryption/OCR preamble (today it runs `fitz.open()` unconditionally, which would crash on every non-PDF).

```
convert_one(task):
  if not src.exists(): return FAILED
  ext = src.suffix.lower()
  if ext == ".pdf":
      run PDF preamble: fitz open → needs_pass? → pikepdf decrypt to work_path
                        → _has_text_layer / page_count → optional ocrmypdf (work_path)
      if fmt == "docx":  _convert_docx(work_path, dst, start, end)
      elif fmt == "md":  _convert_markitdown(work_path, dst)   # decrypted/OCR'd file
  else (non-PDF):
      if fmt == "docx":  return SKIPPED("DOCX output is PDF-only — choose Markdown")
      else:              _convert_markitdown(src, dst)
```

Key points:
- **Encrypted PDF → MD** feeds the **pikepdf-decrypted `work_path`** to markitdown (not `src`).
- **OCR** stays PDF-only and pre-conversion (ocrmypdf → searchable PDF → markitdown). For non-PDF, `--ocr` is inert.
- **Page range** (`start/end`) applies to **PDF→DOCX only**. For any MD output it is ignored; the GUI greys the Pages strip and the CLI warns when a range is set with `--format md` (see §5/§6). The out-of-range `FAILED` guard remains PDF-only.

### 3.2 `_convert_markitdown(src, dst)` + empty-output guard (integrity)
```
from markitdown import MarkItDown            # lazy import inside the function (spawn-safe)
md = MarkItDown(enable_plugins=False, llm_client=<optional>, llm_model=<optional>)
text = md.convert(str(src)).text_content
if not text or not text.strip():
    return NOTEXT("No extractable text (scanned/empty/image-only). ...")   # do NOT write a file
_atomic_write(dst, lambda tmp: tmp.write_text(text.rstrip() + "\n", encoding="utf-8"))
```
This preserves the **"never a silent empty file"** guarantee for *all* input types (scanned PDF, text-less image, empty Office doc). markitdown is imported lazily so workers stay import-cheap and a missing optional dep surfaces as a per-file error.

### 3.3 Status taxonomy
Add a **`SKIPPED`** status constant (for non-PDF + DOCX). Existing `DONE/NOTEXT/FAILED/ENCRYPTED` keep their meaning. Audit/status strings gain `skipped-format` and the empty case maps to `NOTEXT` (counted as skipped, not failed).

### 3.4 Discovery & probe
- `discover_pdfs` → **`discover_files(path, recursive)`** globbing `SUPPORTED_EXTENSIONS`.
- `probe_pdf` → **`probe_file(path)`**: PDFs keep pages/text-layer/encryption probe; non-PDFs resolve straight to `QUEUED` (markitdown reports its own per-file errors at convert time). Pages column shows pages for PDFs, the file type otherwise.

### 3.5 Optional LLM image captions
A config setting (API key / model / base URL). If set, passed to `MarkItDown(llm_client=..., llm_model=...)` for image descriptions. **Off by default** (no key → images yield metadata only → empty-guard → `NOTEXT`).

### 3.6 Dead code removal
Remove the bespoke PyMuPDF Markdown extractor now superseded by markitdown: `_convert_markdown`, `_page_to_markdown`, `_table_to_markdown`, `_format_block`, `fitz_rect`, `_inside_any`, and the now-unused `import statistics`. `resolve_output_path` is already format-agnostic (kept). Output-name collisions across input types (`a.pdf` and `a.docx` → `a.md`) are handled by the existing dedupe/auto-rename (`a (1).md`); overwrite mode unchanged. Documented.

## 4. Output rules (summary)
- **Markdown**: every supported input; empty result → `NOTEXT`, no file written.
- **DOCX**: PDF only; non-PDF → `SKIPPED` (counted as skipped, audit `skipped-format`), never routed into pdf2docx.
- **CLI default format → `md`** (was `docx`); behaviour change noted in CHANGELOG.

## 5. GUI (`gui.py`)
All four PDF-only ingress gates and their copy must change:
- `add_files` filetypes → "All supported files" (full extension list) + per-category groups.
- `_add_paths` suffix check → membership in `engine.SUPPORTED_EXTENSIONS` (currently hard `!= ".pdf"`).
- `add_folder` / drag-drop → `engine.discover_files`; DnD suffix filter → `SUPPORTED_EXTENSIONS`.
- Copy: drop-overlay "Drop files to add", empty-state "Add files or drop a folder", "No supported files found".
- **Pages column**: pages for PDFs, file-type label (DOCX/XLSX/…) otherwise.
- **Page-range Pages strip**: disabled/greyed when format == `md`.
- **DOCX + non-PDF**: queue-level signalling — non-PDF rows show a "DOCX is PDF-only → will be skipped" hint when DOCX is selected (avoids silent mass-skips in a mixed folder).
- **OCR / Unlock** affordances remain PDF-only (shown only for PDF rows); `_STATUS_DISPLAY` gains `SKIPPED`.
- Branding text → MarkItAll + new subtitle. Window icon unchanged.

## 6. CLI (`cli.py`)
- `--input` accepts any supported file/folder via `discover_files`; error message wording generalized.
- `--format` default → `md`. When `--format md` is combined with `--start/--end`, print a clear "page ranges apply to PDF→DOCX only; ignored for Markdown" warning.
- Skip pipeline: non-PDF + `docx` → pre-task `SKIPPED` (clear message, counted as skipped), not routed to the engine as FAILED.

## 7. MCP server (`pdfconv/mcp_server.py`) — new
- **SDK:** official MCP Python SDK — `from mcp.server.fastmcp import FastMCP`; tools via `@mcp.tool()`; run `mcp.run()` (stdio default). (`mcp` ≥ 1.x, MIT, Python ≥3.10 — verified.) Tool functions are plain sync `def` (FastMCP runs them in a thread, so blocking conversions don't stall the loop).
- **Process model:** convert **in-process** (call engine helpers directly, **no ProcessPoolExecutor**) — avoids spawn re-import issues from an installed console script.
- **stdio integrity:** all logging goes to **stderr / the rotating file**, never stdout (stdout is the MCP channel). Ensure no library prints to stdout in the MCP path.
- **Tools:**
  - `convert_to_markdown(path) -> str` — returns Markdown inline. Empty/`NOTEXT`/encrypted/unsupported → **raise** (FastMCP marks `isError`) with a clear message — never returns silent-empty.
  - `convert_file(path, output_format="md"|"docx", output_dir=None) -> {status, message, output_path|null}` — engine status verbatim; failures raise.
  - `list_supported_formats() -> [str]`.
- **Large output:** `convert_to_markdown` returns inline; for very large results recommend `convert_file` (documented). Optional soft size note.
- **SECURITY section (README + design):** server runs with the user's privileges; tools read/write **arbitrary paths**; intended for **local, trusted agents over stdio only**; LLM captions + any remote fetch **off by default**. Mirrors Microsoft `markitdown-mcp`'s documented posture.
- **Packaging:** console script `pdfconv-mcp`; `[mcp]` extra (`mcp`). README documents Claude Desktop/Code wiring **and** Microsoft's `markitdown-mcp` (note: both expose a `convert_to_markdown` tool — use one server at a time).

## 8. Dependencies, license, build
- **Core:** add `markitdown[all]`. Keep pdf2docx, PyMuPDF, customtkinter, pikepdf. `[mcp]` extra = `mcp`. `[dev]` keeps pytest, pyinstaller.
- **Caveats documented in README:** `markitdown[all]` is a large install (onnxruntime via magika, pandas, lxml, Azure SDKs incl. the **pre-release** `azure-ai-contentunderstanding` beta — flagged as a known install caveat). Audio/video deps are installed but **unused** (formats not exposed). No new **copyleft** beyond existing AGPL (markitdown MIT; transitive deps MIT/Apache/BSD) — third-party table updated (markitdown, magika/onnxruntime, pandas, etc.).
- **Frozen build:** the PyInstaller one-file build with onnxruntime/magika is fragile and may not bundle the full markitdown stack; **caveat** in README that the portable binary may be limited and the full feature set is best run from source/pip. (Run-from-source is already the primary path.)

## 9. Testing
Deterministic, offline, Windows-runnable only:
- markitdown path: generate `.docx` / `.html` / `.csv` / `.xlsx` → assert non-empty `.md` with expected text.
- **Empty-output guard**: scanned/blank PDF → `NOTEXT`, **no file**; text-less PNG → `NOTEXT`.
- **Non-PDF + DOCX** → `SKIPPED` (not FAILED).
- Encrypted PDF → MD with correct password → `DONE` (decrypt wired).
- PDF → DOCX still `DONE`.
- Rewrite the old md test (bespoke extractor removed). MCP smoke test: server imports, lists tools, `convert_to_markdown` round-trips a small file; empty input → error.
- Audio/video/URL/LLM-caption paths are **not** auto-tested (network/ffmpeg/keys) — documented as manual.

## 10. Migration / docs
- `CHANGELOG.md`: v2.0 — many formats → Markdown; CLI `--format` default `docx`→`md`; bespoke PyMuPDF md extractor replaced by markitdown; new MCP server; audio/video & URLs are non-goals.
- README: rewritten scope, supported-formats table, install (incl. caveats), MCP setup (ours + Microsoft's), SECURITY note, ffmpeg/Azure-beta caveats.

## 11. Phasing
1. Engine (control-flow, markitdown, empty-guard, statuses, discover/probe, dead-code) + deps.
2. CLI + GUI (gates, copy, page-range gating, skip pipeline, branding).
3. MCP server + packaging.
4. Tests + README/CHANGELOG.
Shipped as **2.0.0**.
