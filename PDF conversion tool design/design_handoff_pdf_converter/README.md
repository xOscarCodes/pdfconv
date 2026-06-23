# Handoff: PDF → DOCX / Markdown Converter

## Overview
A cross-platform (Windows + Linux) desktop utility that converts PDFs to editable Word (`.docx`) **and** Markdown (`.md`) files, supporting single-file and batch (multi-file / whole-folder) conversion, with an optional headless CLI sharing the same engine. The design is a polished, data-first single-window app: a queue of files, a live colour-coded conversion status system (the signature element), an options strip, a footer with progress + log, and a Settings drawer.

This handoff covers the **UI/UX**. The product requirements (functional scope, library contract, acceptance criteria) are defined in the **PRD** — the HTML prototype is the visual and interaction reference for building that PRD.

## About the Design Files
The files in this bundle are **design references created in HTML** — a streaming "Design Component" prototype showing the intended look and behaviour. They are **not production code to copy directly**.

The real product, per the PRD, is a **Python desktop application**:
- GUI: **customtkinter** (committed default; PySide6/Flet are acceptable swaps)
- Engine: **pdf2docx** (`Converter`), plus a Markdown writer (added beyond the original PRD — see note)
- Decryption: **pikepdf** (or PyMuPDF); concurrency via stdlib `concurrent.futures` + `threading`/`queue`
- CLI: stdlib `argparse`; Packaging: **PyInstaller** (build per-OS, no cross-compile)

**Your task:** recreate the look, layout, copy, and interaction model shown in the HTML inside that Python/customtkinter app (or the team's chosen framework). Reproduce the visual system pixel-faithfully where the toolkit allows; where customtkinter can't match exactly (e.g. custom switches, animated dots), approximate with its widgets while keeping the palette, spacing, type scale, and status semantics intact.

> **Markdown note:** the original PRD lists `.md` as a non-goal. The prototype adds Markdown output at the product owner's request. Treat DOCX and Markdown as the two supported output formats. The prototype ships a global DOCX/Markdown toggle and also explores per-file and default+override patterns (see "Format options" view) — confirm which pattern to implement; the app currently wires the **global toggle**.

## Fidelity
**High-fidelity.** Final colours, typography, spacing, radii, and interactions are all intentional. Recreate the UI faithfully. The one place to spend visual effort is the **live status system** (animated converting dot, amber row rail, colour-coded labels, smooth progress, completion flash) — keep all other chrome quiet and disciplined.

---

## Screens / Views

The prototype has a top "prototype navigator" pill (App · Design system · Format options) that is **not part of the product** — it only exists to show the three reference surfaces. Build only the **App** surface; the other two are documentation.

### 1. App (the product) — single resizable window
Opens ~900×640, min ~720×540. Vertical stack inside one window:

1. **OS title bar** (38px) — `surface` bg, 1px bottom `border`. Left: small muted "PDF Converter" label. Right: minimise / maximise / close glyphs (Windows-style; the real app uses native chrome — this is illustrative).
2. **Header** (≈56px) — 1px bottom `border-soft`.
   - Left: 30×30 gradient brand tile (`135deg, accent → accent-hover`, radius 8) containing a white file-check icon, then title **"PDF → DOCX · Markdown"** (16px/600) over subtitle "Convert PDFs to editable documents" (12px `muted`).
   - Right: a **Settings gear** button (32×32, 1px `border`, radius 7), then a 2-button **theme segmented control** (moon / sun) in a `surface` pill.
3. **Action row** (≈58px) — 1px bottom `border-soft`. Left→right: **Convert** (primary, accent), **Add files** (secondary), **Add folder** (secondary), **Clear** (ghost). Right-aligned: an uppercase "FORMAT" label + a **DOCX / Markdown** segmented control.
4. **Selection bar** (conditional) — appears only when ≥1 queue row is selected: `accent-soft` strip with "N selected", "Remove selected" (danger text), "Deselect all" (muted text).
5. **Queue** (flex:1, scrolls) — the main area.
   - **Header row** (sticky, `surface` bg, 1px bottom `border`): select-all checkbox, then uppercase column labels `File · Pages · Format · Status` + a trailing action column. Grid columns: `30px 1fr 64px 60px 158px 30px`, gap 10px, padding 9px 18px.
   - **File rows**: same grid, padding 11px 18px, 1px bottom `border-soft`. Per row:
     - custom checkbox (17×17, radius 4; checked = accent fill + white tick)
     - file icon (17px, `muted`) + filename (13px/500) over mono path (11px `muted`, e.g. `~/Documents`)
     - pages ("12 pp", 12px `muted`)
     - format tag (quiet: 11px/600, `muted`, 70% opacity — "DOCX"/"MD")
     - **status cell**: 8px colour dot (with a 3px 26%-alpha halo ring) + colour-matched label; an amber **inset 2px left rail** on the row while converting; a 4px amber progress bar (max-width 130) under the label while converting; an **Unlock** pill (accent outline + lock icon) when encrypted
     - remove **✕** button (24×24) — hidden by default, **revealed on row hover**; hover turns it `danger`
   - **Empty state** (when queue is empty): centered dashed-border file icon, "No files in the queue", a one-line hint, and Add files / Add folder buttons. The queue is a **drop target** — dragging files over it shows a dashed accent overlay "Drop PDFs to add to the queue".
6. **Options strip** — 1px top `border-soft`, `surface` bg, items separated by 1px vertical dividers (22px tall):
   - **Output**: segmented "Next to source" / "Choose folder…"; when "Choose folder…" is active, a mono path chip appears, plus "· mirroring subfolders" (accent) when that setting is on.
   - **Pages**: two 46×28 numeric inputs (start – end). Invalid range (start > end) turns both borders `danger` and shows a "start ≤ end" message; **Convert is disabled** while invalid.
   - **Overwrite existing**: checkbox.
   - **OCR scanned PDFs**: checkbox.
7. **Footer** — 1px top `border-soft`, `surface` bg:
   - **Summary banner** (after a run): rounded `bg` card, accent check tile, "Conversion complete." + coloured counts "N succeeded · M failed · K skipped".
   - **Progress row**: full-width 8px track (`inset` bg) with accent fill (smooth, includes in-flight fractional progress), then bold count "12 / 50 converted" and a `muted` status word.
   - **Button row**: Cancel (enabled only while running), Retry failed (enabled when last run had failures), Open output folder (enabled after a run), and a right-aligned ▸ **Log** toggle.
   - **Log pane** (collapsible): mono 11.5px, `inset` bg, max-height 150 scroll. Lines are colour-coded by level (ok = green, error = red, warn = amber, info = muted) and timestamped `[HH:MM:SS]`.

### 2. Settings (drawer over the App window)
Right-side drawer (≈380px) clipped to the window's right edge, dim scrim over the app, sticky header ("Settings" + gear + ✕) and a sticky footer with a primary **Done** button. Sections, each separated by a 1px rule:
- **Conversion** — "Parallel workers" with a − / value / + stepper (1–8, default CPU − 1). Caption: "Caps concurrent conversions · default CPU − 1".
- **Output filenames** — Prefix + Suffix text inputs side by side, a live mono preview "report.pdf → `<prefix>report<suffix>.docx`", and a **Mirror source subfolders** toggle switch ("Recreate the folder tree under the output folder").
- **Notifications** — **Notify when a batch completes** toggle switch ("Desktop toast on Windows / Linux").
- **Audit log** — explainer ("Every run is appended: timestamp, source, destination, status, duration."), a mono path chip (`~/.pdfconverter/audit.csv`) + an **Open** button.
- **General** — **Remember folders & preferences** toggle switch ("Persist settings between sessions").

Toggles are iOS-style switches: 34×20 track (accent when on, `border` when off), 16px white knob sliding 2px → 16px, 150ms.

### Documentation-only views (do NOT build as product screens)
- **Design system** — a reference sheet of the tokens (neutrals, accent, status, type, buttons, controls). Use it as the source of truth for values below.
- **Format options** — three explorations of DOCX-vs-Markdown selection (A global toggle, B per-file picker, C default + override). Decide which to ship.

---

## Interactions & Behavior

The prototype **simulates** the engine; the real app performs real conversions with `pdf2docx`. Behaviour to reproduce:

- **Convert**: disabled when the queue is empty, while a run is active, or while the page range is invalid. Starts a batch over the queue (or only the failed items for Retry).
- **Parallelism**: up to *worker-count* files convert **concurrently** (default CPU − 1, settable 1–8). Each active file shows its own progress; the overall bar reflects fractional progress across the batch. *(Real app: process pool via `concurrent.futures`; must work under `fork` (Linux) and `spawn` (Windows) — guard `if __name__ == "__main__":`, keep workers top-level/picklable, call `multiprocessing.freeze_support()` in frozen builds.)*
- **Per-file status lifecycle**: `Queued → Converting → Done`. Special outcomes:
  - **Scanned / no text layer** → status **"No text"** (red). Detect a PDF with no extractable text and mark it instead of writing a silent empty file. If **OCR** is enabled, route it through OCR and convert instead (prototype shows "Running OCR on …" → Done).
  - **Encrypted** → status **"Locked"** (amber) + an **Unlock** action. Unlock opens a password dialog; a correct password decrypts (in memory, pikepdf) and converts; a wrong/empty password errors inline and the batch continues.
  - **Corrupt / unparseable** → status **"Failed"** (red), logged, batch continues (each file isolated in its own try/except).
- **Cancel**: stops cleanly; any in-flight file reverts to Queued. **Never leave a partial output file.**
- **Duplicate handling**: with Overwrite off, a name clash auto-renames `name.docx` → `name (1).docx` (logged); with Overwrite on, it overwrites (logged). Mirror-subfolders prefixes the output path with the source's relative subfolder.
- **End of run**: summary banner (succeeded / failed / skipped), "Open output folder" enabled, "Retry failed" enabled if any failures, run appended to the audit log, and — if notifications are on — a desktop toast.
- **Open output folder**: OS-branch — `os.startfile`/Explorer on Windows, `xdg-open` on Linux.
- **Drag & drop** (P2): files/folders dropped on the window/queue are added.
- **Theme**: dark/light toggle, instant.
- **Reduced motion**: all animations collapse to 0ms under `prefers-reduced-motion`.

### Animation / transition specifics
- Converting status dot: opacity pulse, ~1.1s ease-in-out, infinite.
- Status dot/label colour: 300ms cross-fade on transition.
- Progress bars: width transition ~120–140ms linear.
- Row **completion flash**: brief green-tint background wash (~800ms) when a file finishes.
- Drawers/dialogs/toasts: rise-in ~220–300ms (fade + 10px translate).
- Spinner on the Convert button while running: 0.7s linear rotate.

## State Management
Core state the GUI must track (the prototype's model is a good blueprint):
- `files[]`: `{ id, name, dir, pages, format, status, progress }` where `status ∈ queued | converting | scanning | done | notext | failed | encrypted`.
- `running`, `summary { ok, fail, skip }`, `outputReady`, `log[]` (`{ time, text, level }`), `selection`.
- Options: `format ('docx'|'md')`, `outputMode ('next'|'choose')`, `overwrite`, `pageStart`, `pageEnd`, `ocr`.
- Settings: `workers`, `prefix`, `suffix`, `mirror`, `notify`, `remember`, `theme`.
- **Threading rule (non-functional req):** all conversion happens off the UI thread; widgets are updated only on the main thread via a thread-safe queue.
- **Persistence:** when "Remember" is on, persist settings + last-used folders to a small JSON config and reload on launch.
- **Audit log:** append one record per run (timestamp, source, destination, status, duration) to CSV/JSON.

## Design Tokens

Colours are given as **dark / light**. Status colours are fixed across themes.

| Token | Dark | Light |
|---|---|---|
| `bg` | `#0F172A` | `#F8FAFC` |
| `surface` | `#1E293B` | `#FFFFFF` |
| `inset` (track/log bg) | `#0B1220` | `#F1F5F9` |
| `border` | `#334155` | `#E2E8F0` |
| `border-soft` (hairline) | `#293650` | `#EDF1F6` |
| `text` | `#F1F5F9` | `#0F172A` |
| `muted` | `#94A3B8` | `#64748B` |
| `desktop backdrop` | `#070B16` | `#E2E8F0` |

**Accent (brand, theme-independent):** `--accent #6366F1`, `--accent-hover #4F46E5`, `--accent-soft` = accent at ~18% (dark) / ~10% (light) alpha. Selectable accents in the prototype: indigo `#6366F1`, violet `#7C3AED`, sky `#0EA5E9`, emerald `#10B981`.

**Status (fixed):** Queued `#64748B` · Converting `#F59E0B` · Done `#22C55E` · Failed / No-text `#EF4444` · Encrypted "Locked" uses the amber `#F59E0B` with a lock affordance. Status dots carry a 3px halo at 26% alpha of the dot colour.

**Typography**
- UI font: system sans — Segoe UI (Windows); Inter / Ubuntu / DejaVu Sans / Cantarell (Linux); generic sans fallback.
- Mono: Cascadia Code / Consolas (Windows); DejaVu Sans Mono / Ubuntu Mono (Linux) — used for paths, the log, and figures.
- Scale: page/section title ~16–22px / 600; body & controls 13–14px; captions & badges 11–12px. Tabular numerals on. Weight tops out at 600–700.

**Radius:** controls/inputs 6–7px · cards/window 12–14px · badges/chips 4px · dots/switches/avatars full.

**Spacing:** window gutter 20px; control height 28–34px; row padding 11px×18px; section gaps 18px. Touch/hit targets ≥ the control height.

**Shadows:** surfaces are **border-defined, no shadow**. Shadows are reserved for floating layers (window, drawer, dialog, toast): e.g. window `0 28px 70px -20px rgba(0,0,0,.7)` (dark) / `… rgba(15,23,42,.28)` (light), plus a 1px inset top highlight on the window.

**Focus:** 2px accent ring with a 1px bg offset on `:focus-visible`; inputs shift border to accent (danger on invalid).

**Backdrop:** flat fill + a faint top radial glow (accent ~13%) + a subtle 22px dot grid. No other gradients except the brand tile.

## Assets
- **No logo file.** The brand mark is CSS only: a rounded-square gradient tile (`135deg, accent → accent-hover`) + the "PDF Converter" / title wordmark. Reproduce in the toolkit; do not invent a logo.
- **Icons:** Lucide outline set, 2px stroke, `currentColor`, rendered ~15–16px (file, file-check, folder, plus, x, sun, moon, lock, check, refresh/retry, folder-open, gear, settings-sliders). Use Lucide (or the toolkit's equivalent outline set) — don't hand-draw bespoke glyphs.
- **No emoji** in product chrome.

## Files
- `PDF Converter.dc.html` — the full hi-fi prototype (App + Design system + Format options views). Open it in a browser to interact with the simulated conversion, both themes, all states, and the Settings drawer. `support.js` is the runtime needed to open it.
- Refer to the **PRD** (shared separately in the conversation) for the authoritative functional requirements (FR-1…FR-27), acceptance criteria, platform notes, and deliverables (`pdf2docx_app.py`, `requirements.txt`, `README.md`, PyInstaller build).

## PRD coverage shown in the prototype (quick map)
Shown & faithful: FR-1/2 add files/folder · FR-3 queue · FR-4 remove/clear · FR-7 page range (+validation) · FR-8 parallel workers · FR-9 no-text · FR-10/11 encrypted + unlock · FR-12 OCR toggle · FR-13 output dest · FR-14 overwrite + auto-rename · FR-15 mirror subfolders · FR-16 filename prefix/suffix · FR-17 convert/cancel · FR-18 progress + live count · FR-19 log · FR-20 summary · FR-21 open output · FR-22 retry failed · FR-23 audit-log surface · FR-25 settings persistence · FR-26 dark/light · FR-27 notification preference · FR-5 drag-drop overlay.
Backend-only (implement per PRD, not visible in HTML): real `pdf2docx` conversion (FR-6), real process pool, FR-24 **CLI**, packaging.
