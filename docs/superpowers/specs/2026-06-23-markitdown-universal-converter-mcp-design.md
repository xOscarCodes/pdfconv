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

- **Documents:** `.pdf .docx .pptx .xlsx .xls`
- **Web/text:** `.html .htm .csv .json .xml .txt .md .epub`
- **Archive:** `.zip` (markitdown iterates contents)
- **Outlook:** `.msg`
- **Images:** `.jpg .jpeg .png .gif .bmp .tiff .webp` — EXIF metadata + **optional** LLM caption only (no OCR); text-less images resolve to `NOTEXT` (see §4).

> **Legacy binary Office excluded.** markitdown's converters target OOXML
> (`DocxConverter`/`PptxConverter`/`XlsxConverter` accept only `.docx`/`.pptx`/`.xlsx`),
> so the Word/PowerPoint 97-2003 formats `.doc` and `.ppt` have **no converter** and are
> **not** in `SUPPORTED_EXTENSIONS` (routing them to markitdown would raise
> `UnsupportedFormatException` → surface as `FAILED`, breaking the §4 promise). `.xls` **is**
> included: markitdown ships a dedicated `XlsConverter` (xlrd) under its `xls` extra, which
> `markitdown[all]` (core dep, §8) pulls in. The exact set must be locked against the installed
> markitdown version's converter `accepts()` methods.

**Output formats:** **Markdown** (all inputs) and **DOCX** (PDF input only, via pdf2docx).

## 3. Engine redesign (`engine.py`)

### 3.1 Control flow — the critical fix
`convert_one(task)` must **branch on input type before** the PyMuPDF/encryption/OCR preamble (today it runs `fitz.open()` unconditionally, which would crash on every non-PDF).

```
convert_one(task):
  if not src.exists(): return FAILED
  # LLM-caption keys pulled from the task dict (empty/off by default, §3.5):
  llm_api_key  = task.get("llm_api_key", "")
  llm_model    = task.get("llm_model", "")
  llm_base_url = task.get("llm_base_url", "")
  ext = src.suffix.lower()
  if ext == ".pdf":
      run PDF preamble: fitz open → needs_pass? → pikepdf decrypt to work_path
                        → _has_text_layer / page_count → optional ocrmypdf (work_path)
      if fmt == "docx":  _convert_docx(work_path, dst, start, end)
      elif fmt == "md":  _convert_markitdown(work_path, dst, llm_api_key=llm_api_key,
                                             llm_model=llm_model, llm_base_url=llm_base_url)
  else (non-PDF):
      if fmt == "docx":  return SKIPPED("DOCX output is PDF-only — choose Markdown")
      else:              _convert_markitdown(src, dst, llm_api_key=llm_api_key,
                                             llm_model=llm_model, llm_base_url=llm_base_url)
```

**Where the skip is decided (authoritative):** non-PDF + DOCX is filtered **pre-task in the CLI
and GUI**, before dispatch — matching the existing pre-task skip pattern (`gui.py` `_start_run`
~:1440, `cli.py` task build). Those paths never enqueue the file. **Audit recording differs by
surface, because only the GUI has an audit subsystem:** `cli.py` has **no** audit import or
`append_records` call — its pre-task skip merely increments the `skip` counter and prints a `SKIP`
line (see §6). The **GUI** pre-task filter (in `_start_run`) appends a `skipped-format` audit record
(`{"status": "skipped-format", ...}`), mirroring the existing `skipped-notext`/`skipped-encrypted`
literal-string records it already writes. **Unlike the NOTEXT/ENCRYPTED pre-task blocks (which leave
`item.status` at its meaningful probe value — `NOTEXT`/`ENCRYPTED` — so the row already renders "No
text"/"Locked"), the format-skip branch must additionally set `item.status = engine.SKIPPED` and
refresh the row before `continue`,** because a non-PDF probes to `engine.QUEUED` (§3.4) and would
otherwise keep displaying "Queued". Concretely, in `_start_run`'s `candidates` loop, the branch is
`Path(item.path).suffix.lower() != ".pdf" and fmt == "docx"`: set `item.status = engine.SKIPPED`,
`item.row.refresh()` if a row exists, append the `skipped-format` audit record, increment
`pre_skipped`, log the skip, then `continue` — paralleling the `NOTEXT`/`ENCRYPTED` blocks but with
the extra status assignment so the row renders "Skipped" via the new `_STATUS_DISPLAY` entry (§5) and
becomes re-eligible on a re-run via `start_convert` (§5). The MCP `convert_file` tool applies the same
pre-task filter (§7). `convert_one`'s `return SKIPPED("DOCX output is PDF-only — choose Markdown")` is
retained only as a **defensive fallback** for any direct caller that hands a non-PDF + DOCX task
straight to the engine; when it fires, the engine result carries the bare `SKIPPED` status
(`"skipped"`, §3.3). In the **GUI** result handler (`_apply_result`), that defensive `SKIPPED`
status is mapped to the `skipped-format` audit string before the record is written (§3.3, §5), so
the audit log reads `skipped-format` whether the skip was caught pre-task or via the engine
fallback. The **CLI** result handler counts the fallback `SKIPPED` as a skip (§6) but writes no
audit record (none exists in the CLI).

Key points:
- **Encrypted PDF → MD** feeds the **pikepdf-decrypted `work_path`** to markitdown (not `src`).
- **OCR** stays PDF-only and pre-conversion (ocrmypdf → searchable PDF → markitdown). For non-PDF, `--ocr` is inert.
- **Page range** (`start/end`) applies to **PDF→DOCX only**. For any MD output it is ignored; the GUI greys the Pages strip and the CLI warns when a range is set with `--format md` (see §5/§6). The out-of-range `FAILED` guard remains PDF-only.

### 3.2 `markitdown_text` / `_convert_markitdown` + empty-output guard (integrity)
The convert-and-guard logic is single-sourced in a small helper, `markitdown_text`, which **returns** the extracted Markdown (raising on empty). `_convert_markitdown` is a thin file-writing wrapper over it, and the MCP inline tool calls `markitdown_text` directly (§7):
```
def markitdown_text(src, *, llm_api_key="", llm_model="", llm_base_url="") -> str:
from markitdown import MarkItDown            # lazy import inside the function (spawn-safe)
client = _build_llm_client(llm_api_key, llm_base_url)   # None when llm_api_key is empty (§3.5)
md = MarkItDown(enable_plugins=False,
                llm_client=client,
                llm_model=(llm_model or "gpt-4o") if client else None)
result = md.convert(str(src))
# `.markdown` is markitdown's canonical attribute; `.text_content` is a back-compat alias.
text = getattr(result, "markdown", None) or result.text_content
if not text or not text.strip():
    raise NoTextError("No extractable text (scanned/empty/image-only). ...")
return text.rstrip() + "\n"

def _convert_markitdown(src, dst, *, llm_api_key="", llm_model="", llm_base_url=""):
try:
    text = markitdown_text(src, llm_api_key=llm_api_key, llm_model=llm_model,
                           llm_base_url=llm_base_url)
except NoTextError as e:
    return NOTEXT(str(e))   # do NOT write a file
_atomic_write(dst, lambda tmp: tmp.write_text(text, encoding="utf-8"))
```
`NoTextError` is a small internal exception so the same empty-output check serves both the file-writing path (`_convert_markitdown` maps it to the `NOTEXT` status) and the inline MCP path (`convert_to_markdown` lets it propagate so FastMCP marks `isError`, §7). This preserves the **"never a silent empty file"** guarantee for *all* input types (scanned PDF, text-less image, empty Office doc) and keeps the convert/guard body in one place. markitdown is imported lazily so workers stay import-cheap and a missing optional dep surfaces as a per-file error.

### 3.3 Status taxonomy
Add a **`SKIPPED`** status constant (for non-PDF + DOCX). Its value is a bare word — **`SKIPPED = "skipped"`** — matching the convention of the existing constants (`DONE = "done"`, `NOTEXT = "notext"`, `FAILED = "failed"`, `ENCRYPTED = "encrypted"`). Existing `DONE/NOTEXT/FAILED/ENCRYPTED` keep their meaning.

The audit-string layer gains a new value, **`skipped-format`**, which is **distinct from the `SKIPPED` status constant** — exactly as the existing audit strings `skipped-notext`/`skipped-encrypted` are distinct from the `NOTEXT`/`ENCRYPTED` constants. (The GUI's pre-task records already write these hyphenated literals, not the bare status constants.) `skipped-format` is produced two ways, both **GUI-only** (the CLI has no audit subsystem, §3.1/§6):
- **Pre-task filter** (`gui.py` `_start_run`): writes the literal `{"status": "skipped-format", ...}` record directly.
- **Defensive engine fallback** (`gui.py` `_apply_result`): the engine returns the bare `SKIPPED` (`"skipped"`) status; because the GUI audit record otherwise writes the raw `res["status"]` verbatim (today `_apply_result` does `"status": status`), the fallback is mapped explicitly — **when `status == engine.SKIPPED`, the audited status string is `skipped-format`** (not the raw `"skipped"`). This keeps the audit log consistent regardless of which path fired (see §5).

The empty-output case maps to `NOTEXT`. Both `SKIPPED` and `NOTEXT` are **counted as skipped, not failed** everywhere they are tallied (engine result handling, GUI `_apply_result`, CLI status→tag mapping; see §5/§6).

> **Audit-string mapping is intentionally asymmetric — only `SKIPPED` is remapped.** A *result-path* (engine-returned) `NOTEXT`/`ENCRYPTED` is audited with its **raw** status string (`"notext"`/`"encrypted"`) — `_apply_result` writes `res["status"]` verbatim, unchanged from v1 — while the *pre-task* `NOTEXT`/`ENCRYPTED` skips in `_start_run` already write the distinct hyphenated literals `skipped-notext`/`skipped-encrypted`. The new explicit `status == engine.SKIPPED → "skipped-format"` mapping (above) is therefore added **only** for `SKIPPED`; the result-path `NOTEXT`/`ENCRYPTED` audit strings are deliberately left raw (no behaviour change from v1). This asymmetry is intentional, not an oversight.

### 3.4 Discovery & probe
- `discover_pdfs` → **`discover_files(path, recursive)`** globbing `SUPPORTED_EXTENSIONS`.
- `probe_pdf` → **`probe_file(path)`**: PDFs keep pages/text-layer/encryption probe; non-PDFs resolve straight to `QUEUED` — `probe_file` returns `PdfInfo(pages=0, has_text=True, encrypted=False, error=None)` for them (the explicit `has_text=True` is required: `PdfInfo`'s default is `has_text=False`, which the GUI would map to `NOTEXT`; with `has_text=True`/`encrypted=False`/`error=None` the GUI status-derivation in `_handle_event` falls through to `engine.QUEUED`). markitdown reports its own per-file errors at convert time. The CLI/MCP paths do not probe non-PDFs at all.
- Pages column shows pages for PDFs, the file-type label otherwise. **Mechanism (pinned):** `_pages_label(item)` returns `item.path.suffix.lstrip(".").upper()` (e.g. `DOCX`, `XLSX`) when the suffix is not `.pdf`, otherwise the existing `"{n} pp"` / em-dash. No new `FileItem`/`PdfInfo` field is needed — the path is already on the item, and `probe_file` leaves `info.pages = 0` for non-PDFs (so `item.pages` is `0` and the label is derived solely from the suffix).

### 3.5 Optional LLM image captions
markitdown describes images via an **`llm_client` object** (e.g. an `openai.OpenAI()` instance) plus an `llm_model` name — **not** a bare key string (verified against markitdown docs). So the wiring is:

- **Config keys** (added to `config.DEFAULTS`, all empty/off by default): `llm_api_key: ""`, `llm_model: ""` (e.g. `"gpt-4o"`), `llm_base_url: ""` (optional OpenAI-compatible endpoint).
- **Threading (engine contract):** the three keys are forwarded to the worker on the **`task` dict** as `llm_api_key`/`llm_model`/`llm_base_url` (empty defaults), extending the documented `convert_one` task contract (which currently lists only `id/src/dst/fmt/start/end/overwrite/ocr/password`). `convert_one` pulls them with `task.get(...)` (§3.1) and forwards them as keyword args to `_convert_markitdown(src, dst, *, llm_api_key=..., llm_model=..., llm_base_url=...)` (§3.2). Threading via the task dict (rather than a module-level global) keeps the worker picklable and spawn-safe.
- **Client construction** lives in `_convert_markitdown` via a small `_build_llm_client(llm_api_key, llm_base_url)` helper: when `llm_api_key` is non-empty, lazily `from openai import OpenAI` and build `OpenAI(api_key=llm_api_key, base_url=llm_base_url or None)` (else return `None`), then call `MarkItDown(enable_plugins=False, llm_client=client, llm_model=(llm_model or "gpt-4o") if client else None)`. `enable_plugins` stays **`False`** — markitdown's **built-in** image converter performs captioning from `llm_client` directly; `enable_plugins=True` is only needed for the separate `markitdown-ocr` plugin, which is out of scope.
- **Dependency:** `openai` is **not** in core; it ships in a new `[llm]` extra (§8). When `llm_api_key` is set but `openai` is not installed, the lazy import fails and surfaces as a clear per-file error (captioning unavailable), not a crash.
- **Surfaces:** the keys are read from `config` by the **parent process** (GUI/CLI) when building each task, then carried on the task dict to the worker (so spawn workers see them — see Threading above). GUI exposes them in the settings drawer (API key / model / base URL fields under an "Image captions (optional)" group); CLI reads them from config only (no new flags in v2.0); the MCP server keeps captioning **off** (omits the keys / passes empty defaults) per the §7 security posture.
- **Off by default:** no key → no `llm_client` → images yield EXIF metadata only → empty-guard → `NOTEXT`.

### 3.6 Dead code removal
Remove the bespoke PyMuPDF Markdown extractor now superseded by markitdown: `_convert_markdown`, `_page_to_markdown`, `_table_to_markdown`, `_format_block`, `fitz_rect`, `_inside_any`, and the now-unused `import statistics`. `resolve_output_path` is already format-agnostic (kept). Output-name collisions across input types (`a.pdf` and `a.docx` → `a.md`) are handled by the existing dedupe/auto-rename (`a (1).md`); overwrite mode unchanged. Documented.

## 4. Output rules (summary)
- **Markdown**: every supported input; empty result → `NOTEXT`, no file written.
- **DOCX**: PDF only; non-PDF → `SKIPPED` (counted as skipped; GUI audit string `skipped-format`, §3.3 — the CLI has no audit subsystem), never routed into pdf2docx.
- **CLI default format → `md`** (was `docx`); behaviour change noted in CHANGELOG.

## 5. GUI (`gui.py`)
All four PDF-only ingress gates and their copy must change:
- `add_files` filetypes → "All supported files" (full extension list) + per-category groups.
- `_add_paths` suffix check → membership in `engine.SUPPORTED_EXTENSIONS` (currently hard `!= ".pdf"`).
- `add_folder` / drag-drop → `engine.discover_files`; DnD suffix filter → `SUPPORTED_EXTENSIONS`.
- Copy: drop-overlay "Drop files to add", empty-state "Add files or drop a folder", "No supported files found".
- **Pages column**: pages for PDFs, file-type label (DOCX/XLSX/…) otherwise — implemented in `_pages_label` by returning `item.path.suffix.lstrip(".").upper()` for non-`.pdf` suffixes (no new field; mechanism pinned in §3.4).
- **Page-range Pages strip**: gating keys off the selected **output FORMAT only**, never the queue contents — `md` → greyed/disabled; `docx` → enabled regardless of a mixed queue (so a user can still set a range that applies to the PDF→DOCX subset; non-PDF rows are skipped per §3.1 and ignore `start`/`end` anyway). Greying **preserves** the entered values (visually disabled, not cleared) so switching back to `docx` restores them and `_parse_pages` still feeds `start`/`end` to PDF tasks; greyed-out values are simply not applied while format == `md`.
- **DOCX + non-PDF**: queue-level signalling — non-PDF rows show a "DOCX is PDF-only → will be skipped" hint when DOCX is selected (avoids silent mass-skips in a mixed folder).
- **OCR / Unlock** affordances remain PDF-only (shown only for PDF rows).
- **Image captions (optional) settings group** (the API key / model / base URL fields, §3.5): when `import openai` is **unavailable** (the `[llm]` extra isn't installed, §8), the GUI **greys/disables the group and annotates it** with an `install pdfconv[llm]` hint, so a user gets an up-front signal instead of entering a key and silently hitting the per-file import error (§3.5) on every image. When `openai` imports cleanly the fields are enabled normally; the per-file error remains the fallback for runtime issues (bad key/endpoint). The availability probe is a one-time `importlib.util.find_spec("openai")` at drawer build (no eager `import openai`, keeping the import lazy per §3.5).
- **`SKIPPED` status wiring** (a bare `_STATUS_DISPLAY` entry is not enough — every place that branches on status must treat `SKIPPED` like the existing skip statuses):
  - `_STATUS_DISPLAY` gains `SKIPPED` → e.g. `("Skipped", theme.ST_CONV)` (the same muted colour `ENCRYPTED` rows use today — `engine.ENCRYPTED: ("Locked", theme.ST_CONV)`). Note: today's `_STATUS_DISPLAY` maps `engine.NOTEXT: ("No text", theme.ST_FAIL)`, i.e. `NOTEXT` IS rendered in the red/fail colour despite being *counted* as a skip (§3.3). Aligning `NOTEXT`'s colour with the skip palette is a possible separate change but is **not** in scope here; this entry only adds `SKIPPED → ST_CONV`. This entry is what renders the pre-task-skipped row: the `_start_run` format-skip branch sets `item.status = engine.SKIPPED` and refreshes the row before `continue` (§3.1), so the row shows "Skipped" instead of staying at its probe status (`QUEUED` for a non-PDF, §3.4). Without that status assignment this entry would be dead for the pre-task path.
  - `_apply_result` (~:1635): add `SKIPPED` to the `NOTEXT/ENCRYPTED` **skip** branch so it increments `summary["skip"]` and does **not** fall through to the else branch that increments `summary["fail"]` and sets `had_failures = True`.
  - `_apply_result` audit mapping (~:1642): the audit record today writes the raw status verbatim (`"status": status`). For the defensive `SKIPPED` fallback this must instead record the `skipped-format` audit string — write `"skipped-format" if status == engine.SKIPPED else status` (§3.3), so the engine-fallback audit record matches the pre-task `skipped-format` string and is never logged as the bare `"skipped"`.
  - `start_convert` eligible set (~:1383): add `engine.SKIPPED` so a re-run can re-evaluate a previously-skipped row (e.g. after switching format to `md`) instead of leaving it stuck.
  - The summary banner already renders the aggregate `summary["skip"]` count, so once the tally is fixed it needs no further change; no separate per-status banner colour map exists.
  - Note: with the §3.1 pre-task filter, non-PDF + DOCX is normally caught in `_start_run`, which sets `item.status = engine.SKIPPED` (so the row renders "Skipped" via the entry above) and audits `skipped-format` before dispatch; the two `_apply_result` changes above cover the defensive engine fallback — the skip-branch change keeps a `SKIPPED` result from being miscounted as a failure, and the audit-mapping change records it as `skipped-format` rather than the bare `"skipped"` status.
- Branding text → MarkItAll + new subtitle. Window icon unchanged.

## 6. CLI (`cli.py`)
- `--input` accepts any supported file/folder via `discover_files`; error message wording generalized.
- `--format` default → `md`. When `--format md` is combined with `--start/--end`, print a clear "page ranges apply to PDF→DOCX only; ignored for Markdown" warning.
- Skip pipeline: non-PDF + `docx` → pre-task `SKIPPED` (clear message, counted as skipped), **never submitted to the executor** (not routed to the engine as FAILED). Because the CLI's `ok/fail/skip` counters and the per-file `[done/total] TAG name` line live **inside** the results loop (`cli.py` ~:107–125) which iterates only the dispatched `tasks`, the pre-task skip must be reconciled outside that loop so the numbers add up. **Structure (pinned), mirroring how `gui._start_run` seeds `summary["skip"]=pre_skipped` and sets `run_total=len(tasks)`:**
  - While building `tasks`, count a `pre_skipped` integer for each non-PDF + `docx` input (excluded from the `tasks` list) and, at build time, print its `SKIP` line and log the reason.
  - Set `total = len(tasks) + pre_skipped` (so `[done/total]` still reconciles for the dispatched files), and seed `skip = pre_skipped` before the results loop (alongside `ok = fail = 0`, `done = 0`).
  - Include `pre_skipped` in the final `Done: … succeeded · … failed · … skipped` summary (already covered once `skip` is seeded).
  This keeps `done` (incremented per dispatched future) ≤ `total`, with the pre-skipped files reflected in `total` and the `skip` tally but not in the per-future loop.
- Status→tag mapping (`run`, ~:116-124): add `engine.SKIPPED` to the `NOTEXT/ENCRYPTED` branch that maps to the `SKIP` tag and the `skip` counter, so the defensive engine fallback (and any directly-returned `SKIPPED`) counts as skipped rather than falling into the `FAIL` else branch (which would also flip the non-zero exit code).

## 7. MCP server (`pdfconv/mcp_server.py`) — new
- **SDK:** official MCP Python SDK — `from mcp.server.fastmcp import FastMCP`; tools via `@mcp.tool()`; run `mcp.run()` (stdio default). Pin **`mcp>=1.10,<2`** (MIT, Python ≥3.10 — verified), mirroring the bounded-pin discipline of `markitdown>=0.1,<0.2`. The upper bound is required: the in-progress **v2** SDK renames `FastMCP` → `MCPServer` (import moves from `mcp.server.fastmcp.*` to `mcp.server.mcpserver.*`) and changes the error model (`McpError` → `MCPError`/`ToolError`), so an unbounded `mcp` would resolve to a 2.x that breaks the `mcp.server.fastmcp` import at install time. Migrating to the v2 `MCPServer` API is a documented future caveat, not a v2.0 task. Tool functions are plain sync `def` (FastMCP runs them in a thread, so blocking conversions don't stall the loop).
- **Process model:** convert **in-process** (call engine helpers directly, **no ProcessPoolExecutor**) — avoids spawn re-import issues from an installed console script.
- **stdio integrity:** all logging goes to **stderr / the rotating file**, never stdout (stdout is the MCP channel). Ensure no library prints to stdout in the MCP path.
- **Tools:**
  - `convert_to_markdown(path) -> str` — returns Markdown inline. Empty/`NOTEXT`/encrypted/unsupported → **raise** (FastMCP marks `isError`) with a clear message — never returns silent-empty.
    - **Engine call (exact):** this tool returns text **inline**, so it does **not** go through `_convert_markitdown`/`convert_one` (which write a file and return a status dict). It calls the single-sourced helper `engine.markitdown_text(work_path, *, llm_api_key="", llm_model="", llm_base_url="") -> str` (§3.2), which wraps the same `MarkItDown(...).convert(...)` body and **empty-output guard** but **returns the text** instead of writing it, raising `NoTextError` with the engine NOTEXT message (`"No extractable text (scanned/empty/image-only). ..."`) on an empty/whitespace result. The tool lets `NoTextError` (and `MarkItDown`'s `UnsupportedFormatException` / `FileConversionException`) propagate so FastMCP marks `isError`. The flow:
      - **For `.pdf`:** reuse the §3.1 PDF preamble in-process to obtain a usable `work_path` — open with `fitz`, and if `doc.needs_pass` **raise** with the engine `ENCRYPTED` message (`"Password required."`, §3.1; the MCP path supplies no password in v2.0, so an encrypted PDF surfaces as a clean "encrypted → raise", never handed to markitdown un-decrypted). The text-layer/OCR steps are **not** run for the inline tool (OCR is off from MCP per the §7 defaults); a scanned/text-less PDF therefore falls through to `markitdown_text`'s empty-output guard and raises `NoTextError`. Then call `markitdown_text(work_path, ...)`.
      - **For non-PDFs:** call `markitdown_text(path, ...)` directly (same guard).
    - **Captioning (pinned off):** `convert_to_markdown` builds **no** `llm_client` — it passes the empty `llm_*` defaults (`llm_api_key=""`, `llm_model=""`, `llm_base_url=""`) into `markitdown_text`, which forwards them to `_build_llm_client` (→ `None` when the key is empty, §3.5), so captioning is **off** on this inline path exactly as it is for `convert_file` (§7 SECURITY posture). This matches the §3.5 off-by-default guarantee end-to-end: no key → no `llm_client` → images yield EXIF only → empty-guard → raise.
  - `convert_file(path, output_format="md"|"docx", output_dir=None) -> {status, message, output_path|null}` — engine status verbatim; failures raise.
    - **Engine call (exact):** build a task dict and call `engine.convert_one(task)` in-process (the existing worker; no new public helper). `dst` is pre-resolved with `engine.resolve_output_path(Path(path), output_format, "choose" if output_dir else "next", Path(output_dir) if output_dir else None, overwrite=False)`. Documented task defaults for the MCP path: `id=0`, `start=None`, `end=None`, `ocr=False`, `overwrite=False`, `password=None`, `llm_api_key=""`, `llm_model=""`, `llm_base_url=""` (no decryption/OCR/page-range from MCP in v2.0; captioning off — empty `llm_*` keys, per the SECURITY posture below). For `output_format="docx"` with a non-PDF input, apply the same §3.1 pre-task filter — return the `SKIPPED` status (the response `status` field is the bare `"skipped"` constant, §3.3) rather than dispatching to the engine. (The MCP server has no audit subsystem, so the GUI-only `skipped-format` audit string, §3.3, does not apply here; the JSON return carries the `SKIPPED` status, not an audit record.)
    - **Return mapping:** `status`/`message` come straight from the engine result; `output_path` = the result's `dst` **only when status is `DONE`**, else `null` (a half-/non-written file is never advertised). `NOTEXT`/`ENCRYPTED`/`SKIPPED` return with `output_path: null` and the engine message; only hard `FAILED` (and missing/unsupported input) **raises** (FastMCP `isError`).
  - `list_supported_formats() -> [str]`.
- **Large output:** `convert_to_markdown` returns inline; for very large results recommend `convert_file` (documented). Optional soft size note.
- **SECURITY section (README + design):** server runs with the user's privileges; tools read/write **arbitrary paths**; intended for **local, trusted agents over stdio only**; LLM captions + any remote fetch **off by default**. Mirrors Microsoft `markitdown-mcp`'s documented posture.
- **Packaging:** add console script `pdfconv-mcp = "pdfconv.mcp_server:main"`; `[mcp]` extra (`mcp>=1.10,<2`). README documents Claude Desktop/Code wiring **and** Microsoft's `markitdown-mcp` (note: both expose a `convert_to_markdown` tool — use one server at a time; and the argument contracts differ — ours takes a local filesystem `path` (routed via markitdown's `convert_local`), whereas Microsoft's takes a `uri` (`http:`/`https:`/`file:`/`data:`, routed via `convert_uri`)).
- **Existing names kept (no rename, avoid breaking users):** `[project].name` stays `pdfconv`; the existing console scripts `pdf2docx`/`pdf2docx-gui`, the root `pdf2docx_app.py` shim, and the CLI `prog="pdf2docx_app"` / its `description` help string are **unchanged** (the "MarkItAll" rebrand is UI/marketing copy only — window title, About dialog, README — not the entry-point identifiers). Only `[project].version` bumps `1.0.0` → `2.0.0` and `[project].description`/keywords are broadened to mention Markdown-from-many-formats + MCP.

## 8. Dependencies, license, build
- **Core:** add `markitdown[all]` (pinned to a range that still exposes `DocumentConverterResult.markdown` and the `text_content` alias — `markitdown>=0.1,<0.2`). Keep pdf2docx, PyMuPDF, customtkinter, pikepdf. `[mcp]` extra = `mcp>=1.10,<2` (bounded so the `from mcp.server.fastmcp import FastMCP` import survives the v2 `MCPServer` rename — see §7). `[llm]` extra = `openai` (only needed for optional image captions, §3.5). `[dev]` keeps pytest, pyinstaller.
- **Caveats documented in README:** `markitdown[all]` is a large install (onnxruntime via magika, pandas, lxml, Azure SDKs incl. the **pre-release** `azure-ai-contentunderstanding` beta — flagged as a known install caveat). Audio/video deps are installed but **unused** (formats not exposed). No new **copyleft** beyond existing AGPL (markitdown MIT; transitive deps MIT/Apache/BSD) — third-party table updated (markitdown, magika/onnxruntime, pandas, etc.).
- **Frozen build:** the PyInstaller one-file build with onnxruntime/magika is fragile and may not bundle the full markitdown stack; **caveat** in README that the portable binary may be limited and the full feature set is best run from source/pip. (Run-from-source is already the primary path.)

## 9. Testing
Deterministic, offline, Windows-runnable only:
- markitdown path: generate `.docx` / `.html` / `.csv` / `.xlsx` → assert non-empty `.md` with expected text.
- **Empty-output guard**: scanned/blank PDF → `NOTEXT`, **no file**; text-less PNG → `NOTEXT`.
- **Non-PDF + DOCX** → `SKIPPED` (not FAILED).
- Encrypted PDF → MD with correct password → `DONE` (decrypt wired).
- PDF → DOCX still `DONE`.
- Rewrite the old md test (bespoke extractor removed): `test_convert_markdown_contains_text` currently asserts on the deleted PyMuPDF output, so rewrite it to assert markitdown output — the PDF→MD path now flows through `_convert_markitdown` (§3.2), so the test should still feed a small text PDF and assert the expected text appears in the `.md`, now produced by markitdown rather than the bespoke extractor.
- **Test contract tracks the engine contract (from §3.1/§3.5):** update the `_task` helper in `tests/test_engine.py` and the `convert_one` task-contract docstring so both gain the `llm_api_key`/`llm_model`/`llm_base_url` keys with empty defaults (alongside the existing `id/src/dst/fmt/start/end/overwrite/ocr/password`), so the test task shape does not silently diverge from the new engine task shape.
- MCP smoke test: server imports, lists tools, `convert_to_markdown` round-trips a small file; empty input → error.
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
