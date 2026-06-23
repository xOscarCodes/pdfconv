"""Smoke tests for the conversion engine.

Fast and self-contained: each test generates its own tiny PDF with PyMuPDF, so
there are no fixtures to ship and no network access. Run with::

    pip install pytest
    pytest
"""
from __future__ import annotations

import zipfile
from pathlib import Path

import fitz  # PyMuPDF
import pytest

from pdfconv import engine


def _make_pdf(path: Path, text: str = "Hello World", pages: int = 1,
              encrypt: str | None = None) -> Path:
    doc = fitz.open()
    try:
        for i in range(pages):
            page = doc.new_page()
            page.insert_text((72, 72), f"{text} {i}")
        if encrypt:
            doc.save(str(path), encryption=fitz.PDF_ENCRYPT_AES_256,
                     owner_pw=encrypt, user_pw=encrypt)
        else:
            doc.save(str(path))
    finally:
        doc.close()
    return path


def _task(src: Path, dst: Path, fmt: str, **kw) -> dict:
    task = {"id": 0, "src": str(src), "dst": str(dst), "fmt": fmt,
            "start": None, "end": None, "overwrite": True, "ocr": False,
            "password": None}
    task.update(kw)
    return task


def test_probe_text_pdf(tmp_path):
    src = _make_pdf(tmp_path / "a.pdf")
    info = engine.probe_pdf(str(src))
    assert info.error is None
    assert info.pages == 1
    assert info.has_text is True
    assert info.encrypted is False


def test_convert_docx_produces_valid_docx(tmp_path):
    src = _make_pdf(tmp_path / "a.pdf")
    dst = tmp_path / "a.docx"
    res = engine.convert_one(_task(src, dst, "docx"))
    assert res["status"] == engine.DONE, res
    assert dst.exists()
    # A .docx is a zip archive containing word/document.xml.
    with zipfile.ZipFile(dst) as zf:
        assert "word/document.xml" in zf.namelist()


def test_convert_markdown_contains_text(tmp_path):
    src = _make_pdf(tmp_path / "a.pdf", text="Hello Markdown")
    dst = tmp_path / "a.md"
    res = engine.convert_one(_task(src, dst, "md"))
    assert res["status"] == engine.DONE, res
    assert dst.exists()
    assert "Hello Markdown" in dst.read_text(encoding="utf-8")


def test_corrupt_pdf_is_isolated(tmp_path):
    bad = tmp_path / "bad.pdf"
    bad.write_text("this is definitely not a pdf", encoding="utf-8")
    info = engine.probe_pdf(str(bad))
    assert info.error is not None  # never raises, reports via error
    res = engine.convert_one(_task(bad, tmp_path / "bad.docx", "docx"))
    assert res["status"] == engine.FAILED


def test_encrypted_pdf_reported_then_unlocked(tmp_path):
    src = _make_pdf(tmp_path / "enc.pdf", encrypt="s3cret")
    info = engine.probe_pdf(str(src))
    assert info.encrypted is True
    # No password -> reported as ENCRYPTED, never a silent empty file.
    res = engine.convert_one(_task(src, tmp_path / "enc.docx", "docx"))
    assert res["status"] == engine.ENCRYPTED
    # Correct password -> converts.
    res2 = engine.convert_one(
        _task(src, tmp_path / "enc.docx", "docx", password="s3cret"))
    assert res2["status"] == engine.DONE, res2


def test_page_range_past_end_fails_clearly(tmp_path):
    src = _make_pdf(tmp_path / "a.pdf", pages=2)
    res = engine.convert_one(_task(src, tmp_path / "a.docx", "docx", start=5))
    assert res["status"] == engine.FAILED
    assert "past the last page" in res["message"]


def test_no_partial_output_on_overwrite_off(tmp_path):
    # Auto-rename when overwrite is off and the destination already exists.
    src = _make_pdf(tmp_path / "a.pdf")
    existing = tmp_path / "a.md"
    existing.write_text("pre-existing", encoding="utf-8")
    dst = engine.resolve_output_path(src, "md", "next", None, overwrite=False)
    assert dst != existing
    assert dst.name == "a (1).md"
